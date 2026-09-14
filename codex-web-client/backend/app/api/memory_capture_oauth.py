from __future__ import annotations

import secrets
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.api.auth import source_ip
from app.auth.passwords import verify_password
from app.auth.sessions import COOKIE_NAME
from app.handoff.oauth_protocol import (
    PKCE_VERIFIER_PATTERN,
    AuthorizationRequest,
    OAuthRequestError,
    pkce_challenge,
    read_signed_authorization_request,
    sign_authorization_request,
    validate_redirect_uri,
    validate_resource,
)
from app.handoff.oauth_store import OAuthGrant
from app.hub.oauth import hub_oauth_urls
from app.memory_capture.consent import capture_authorization_page
from app.memory_capture.oauth import (
    OFFLINE_SCOPE,
    READ_SCOPE,
    WRITE_SCOPE,
    canonical_memory_scope,
    memory_oauth_urls,
)


router = APIRouter(prefix="/api/memory/oauth")


def _error(error: str, description: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse(
        {"error": error, "error_description": description},
        status_code=status_code,
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


def _string_list(metadata: dict, key: str, default: list[str]) -> list[str]:
    value = metadata.get(key, default)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise OAuthRequestError("invalid_client_metadata", f"{key} must be a string array")
    return value


def _configured_route_ids(request: Request) -> tuple[str, ...]:
    """Resident MCP routes come from trusted startup config, never from a caller."""
    memory_mcp = request.app.state.memory_mcp
    if memory_mcp is not None:
        return memory_mcp.registry.mcp_route_ids
    hub_mcp = getattr(request.app.state, "hub_mcp", None)
    if hub_mcp is not None:
        return hub_mcp.registry.mcp_route_ids
    return ()


def _validate_configured_resource(request: Request, resource: str) -> str:
    """Accept only an exact resource URL backed by the startup registry.

    The same owner-authorized issuer serves both the Memory MCP and the Home
    Plugin Hub MCP. Each route publishes both resource URLs, so a token issued
    for one door can never open the other.
    """
    candidates = [memory_oauth_urls(request).resource]
    for route_id in _configured_route_ids(request):
        candidates.append(memory_oauth_urls(request, route_id).resource)
        candidates.append(hub_oauth_urls(request, route_id).resource)
    for candidate in candidates:
        try:
            return validate_resource(resource, candidate)
        except OAuthRequestError:
            continue
    raise OAuthRequestError("invalid_target", "resource is not a configured MCP resource")


@router.get("/.well-known/oauth-authorization-server")
def authorization_metadata(request: Request) -> dict:
    urls = memory_oauth_urls(request)
    return {
        "issuer": urls.issuer,
        "authorization_endpoint": urls.authorization_endpoint,
        "token_endpoint": urls.token_endpoint,
        "revocation_endpoint": urls.revocation_endpoint,
        "registration_endpoint": urls.registration_endpoint,
        "scopes_supported": [READ_SCOPE, WRITE_SCOPE, OFFLINE_SCOPE],
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
    }


@router.post("/register")
async def register(request: Request):
    if not request.app.state.handoff_registration_limiter.allow(source_ip(request)):
        return _error("temporarily_unavailable", "registration rate limit exceeded", 429)
    try:
        metadata = await request.json()
        if not isinstance(metadata, dict):
            raise OAuthRequestError("invalid_client_metadata", "metadata must be an object")
        redirects = tuple(validate_redirect_uri(uri) for uri in _string_list(metadata, "redirect_uris", []))
        if not redirects or len(redirects) > 4 or len(set(redirects)) != len(redirects):
            raise OAuthRequestError("invalid_redirect_uri", "one to four callbacks are required")
        if metadata.get("token_endpoint_auth_method", "none") != "none":
            raise OAuthRequestError("invalid_client_metadata", "only public clients are supported")
        if _string_list(metadata, "response_types", ["code"]) != ["code"]:
            raise OAuthRequestError("invalid_client_metadata", "only code response is supported")
        default_scope = f"{READ_SCOPE} {WRITE_SCOPE} {OFFLINE_SCOPE}"
        scope = canonical_memory_scope(str(metadata.get("scope", default_scope)))
        name = str(metadata.get("client_name", "ChatGPT Continuum Memory"))
        if not name.strip() or len(name) > 120:
            raise OAuthRequestError("invalid_client_metadata", "client_name is invalid")
    except (TypeError, ValueError) as error:
        if isinstance(error, OAuthRequestError):
            return _error(error.error, error.description)
        return _error("invalid_client_metadata", "registration body is invalid")
    client = request.app.state.memory_oauth.register_client(
        redirect_uris=redirects,
        client_name=name.strip(),
        scope=scope,
    )
    return JSONResponse(
        {
            "client_id": client.client_id,
            "client_id_issued_at": client.created_at,
            "client_name": client.client_name,
            "redirect_uris": list(client.redirect_uris),
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "scope": client.scope,
        },
        status_code=201,
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


def _authorization_request(request: Request, values: dict[str, str]) -> AuthorizationRequest:
    client = request.app.state.memory_oauth.read_client(values["client_id"])
    if client is None or values["redirect_uri"] not in client.redirect_uris:
        raise OAuthRequestError("unauthorized_client", "unknown client or callback")
    if values["response_type"] != "code":
        raise OAuthRequestError("unsupported_response_type", "only code is supported")
    if values["code_challenge_method"] != "S256" or not PKCE_VERIFIER_PATTERN.fullmatch(values["code_challenge"]):
        raise OAuthRequestError("invalid_request", "PKCE S256 is required")
    if not values["state"]:
        raise OAuthRequestError("invalid_request", "state is required")
    return AuthorizationRequest(
        client_id=client.client_id,
        redirect_uri=validate_redirect_uri(values["redirect_uri"]),
        resource=_validate_configured_resource(request, values["resource"]),
        scope=canonical_memory_scope(values["scope"]),
        state=values["state"],
        code_challenge=values["code_challenge"],
    )


@router.get("/authorize")
def authorize(
    request: Request,
    response_type: str = "",
    client_id: str = "",
    redirect_uri: str = "",
    scope: str = "",
    state: str = "",
    code_challenge: str = "",
    code_challenge_method: str = "",
    resource: str = "",
):
    try:
        request_data = _authorization_request(request, locals())
    except OAuthRequestError as error:
        return _error(error.error, error.description)
    token = sign_authorization_request(request_data, request.app.state.settings.session_secret)
    return capture_authorization_page(request_data, token)


def _redirect(request_data: AuthorizationRequest, **parameters: str) -> RedirectResponse:
    parameters["state"] = request_data.state
    separator = "&" if urlsplit(request_data.redirect_uri).query else "?"
    return RedirectResponse(
        f"{request_data.redirect_uri}{separator}{urlencode(parameters)}",
        status_code=303,
    )


@router.post("/authorize")
async def approve(request: Request):
    form = await request.form()
    try:
        request_data = read_signed_authorization_request(
            str(form.get("request_token", "")),
            request.app.state.settings.session_secret,
        )
        _validate_configured_resource(request, request_data.resource)
        canonical_memory_scope(request_data.scope)
    except OAuthRequestError as error:
        return _error(error.error, error.description)
    if form.get("decision") != "approve":
        return _redirect(request_data, error="access_denied")
    session = request.app.state.sessions.read(request.cookies.get(COOKIE_NAME))
    user_id = session.user_id if session else None
    if user_id is None:
        # This is a single-owner VPS: the configured account is authoritative.
        username = request.app.state.settings.bootstrap_username
        password = str(form.get("owner_password", form.get("password", "")))
        origin = source_ip(request)
        if not request.app.state.limiter.allowed(origin, username):
            return capture_authorization_page(request_data, str(form["request_token"]), "Try again later.", 429)
        with request.app.state.db.connect() as connection:
            row = connection.execute(
                "SELECT id,password_hash FROM users WHERE username=?",
                (username,),
            ).fetchone()
        valid = row is not None and verify_password(row["password_hash"], password)
        if not valid:
            request.app.state.limiter.failure(origin, username)
            return capture_authorization_page(request_data, str(form["request_token"]), "Invalid credentials.", 401)
        request.app.state.limiter.success(origin, username)
        user_id = int(row["id"])
    code = request.app.state.memory_oauth.create_code(
        user_id=user_id,
        client_id=request_data.client_id,
        redirect_uri=request_data.redirect_uri,
        resource=request_data.resource,
        scope=request_data.scope,
        code_challenge=request_data.code_challenge,
        ttl_seconds=request.app.state.settings.handoff_oauth_code_ttl_seconds,
    )
    return _redirect(request_data, code=code)


def _token_response(request: Request, grant: OAuthGrant) -> JSONResponse:
    settings = request.app.state.settings
    access, refresh = request.app.state.memory_oauth.issue_tokens(
        grant,
        access_ttl_seconds=settings.handoff_oauth_access_ttl_seconds,
        refresh_ttl_seconds=settings.handoff_oauth_refresh_ttl_seconds,
        include_refresh_token=OFFLINE_SCOPE in grant.scope.split(),
    )
    body = {"access_token": access, "token_type": "Bearer", "expires_in": settings.handoff_oauth_access_ttl_seconds, "scope": grant.scope}
    if refresh:
        body["refresh_token"] = refresh
    return JSONResponse(body, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})


@router.post("/token")
async def token(request: Request):
    form = await request.form()
    client_id = str(form.get("client_id", ""))
    client = request.app.state.memory_oauth.read_client(client_id)
    required_scopes = {READ_SCOPE, WRITE_SCOPE}
    if client is None or not required_scopes.issubset(client.scope.split()):
        return _error("invalid_client", "unknown Continuum Memory client", 401)
    resource = str(form.get("resource", ""))
    try:
        _validate_configured_resource(request, resource)
    except OAuthRequestError as error:
        return _error(error.error, error.description)
    grant_type = str(form.get("grant_type", ""))
    if grant_type == "authorization_code":
        challenge = pkce_challenge(str(form.get("code_verifier", "")))
        code = request.app.state.memory_oauth.consume_code(
            str(form.get("code", "")),
            client_id=client_id,
            redirect_uri=str(form.get("redirect_uri", "")),
            resource=resource,
            code_challenge=challenge or "",
        )
        if code is None:
            return _error("invalid_grant", "authorization code is invalid or expired")
        grant = OAuthGrant(code.user_id, client_id, resource, code.scope, secrets.token_urlsafe(24))
        return _token_response(request, grant)
    if grant_type == "refresh_token":
        grant = request.app.state.memory_oauth.rotate_refresh_token(str(form.get("refresh_token", "")))
        if grant is None or grant.client_id != client_id or grant.resource != resource:
            return _error("invalid_grant", "refresh token is invalid or expired")
        requested_scope = str(form.get("scope", grant.scope))
        try:
            requested_scope = canonical_memory_scope(requested_scope)
        except OAuthRequestError as error:
            return _error(error.error, error.description)
        if not set(requested_scope.split()).issubset(set(grant.scope.split())):
            return _error("invalid_scope", "refresh cannot expand scopes")
        return _token_response(request, OAuthGrant(**{**grant.__dict__, "scope": requested_scope}))
    return _error("unsupported_grant_type", "grant type is not supported")


@router.post("/revoke")
async def revoke(request: Request):
    form = await request.form()
    request.app.state.memory_oauth.revoke(str(form.get("token", "")))
    return JSONResponse({}, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})


metadata_router = APIRouter()


@metadata_router.get("/.well-known/oauth-authorization-server/api/memory/oauth")
def standard_authorization_metadata(request: Request) -> dict:
    """Expose RFC 8414 discovery at the issuer-derived well-known path."""
    return authorization_metadata(request)


@metadata_router.get("/.well-known/oauth-protected-resource/api/memory/mcp")
def protected_resource_metadata(request: Request) -> dict:
    urls = memory_oauth_urls(request)
    return {
        "resource": urls.resource,
        "authorization_servers": [urls.issuer],
        "scopes_supported": [READ_SCOPE, WRITE_SCOPE, OFFLINE_SCOPE],
        "bearer_methods_supported": ["header"],
        "resource_name": "Continuum Memory MCP",
    }


@metadata_router.get(
    "/.well-known/oauth-protected-resource/api/memory/mcp/{route_id}"
)
def resident_protected_resource_metadata(route_id: str, request: Request) -> dict:
    try:
        request.app.state.memory_mcp.resolve_route(route_id)
    except (AttributeError, ValueError) as error:
        return _error("invalid_target", str(error), 404)
    urls = memory_oauth_urls(request, route_id)
    return {
        "resource": urls.resource,
        "authorization_servers": [urls.issuer],
        "scopes_supported": [READ_SCOPE, WRITE_SCOPE, OFFLINE_SCOPE],
        "bearer_methods_supported": ["header"],
        "resource_name": f"Continuum Memory MCP ({route_id})",
    }
