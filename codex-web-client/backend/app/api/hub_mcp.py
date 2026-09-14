"""Expose the Home Plugin Hub as a remote MCP endpoint for approved Apps."""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request, Response

from app.hub.oauth import hub_oauth_urls
from app.memory_capture.oauth import READ_SCOPE, WRITE_SCOPE
from plugin_hub.client import HubClientError


router = APIRouter()


def _authorize(
    request: Request,
    authorization: str | None,
    *,
    route_id: str,
):
    scheme, separator, token = (authorization or "").partition(" ")
    grant = None
    if separator and scheme.lower() == "bearer":
        grant = request.app.state.memory_oauth.read_access_token(
            token,
            hub_oauth_urls(request, route_id).resource,
        )
    if grant is not None and {READ_SCOPE, WRITE_SCOPE}.issubset(grant.scope.split()):
        return grant
    urls = hub_oauth_urls(request, route_id)
    raise HTTPException(
        401,
        "home plugin hub authorization required",
        headers={
            "WWW-Authenticate": (
                'Bearer realm="home-plugin-hub", '
                f'resource_metadata="{urls.protected_resource_metadata}", '
                f'scope="{WRITE_SCOPE}"'
            )
        },
    )


def _error_response(request_id, code: int, message: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _mcp_response(
    request: Request,
    body: dict,
    authorization: str | None,
    *,
    route_id: str,
):
    hub = request.app.state.hub_mcp
    if hub is None:
        raise HTTPException(503, "home plugin hub bridge is not configured")
    try:
        route = hub.resolve_route(route_id)
    except ValueError as error:
        raise HTTPException(404, str(error)) from error
    grant = _authorize(request, authorization, route_id=route_id)
    client_host = request.client.host if request.client else "unknown"
    client_key = f"hub:{route_id}:{grant.user_id}:{grant.client_id}:{client_host}"
    if not request.app.state.hub_mcp_limiter.allow(client_key):
        raise HTTPException(429, "home plugin hub rate limit exceeded")
    method = body.get("method")
    request_id = body.get("id")
    if method == "notifications/initialized":
        return Response(status_code=204)
    if method == "initialize":
        result = {
            "protocolVersion": "2025-06-18",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "home-plugin-hub", "version": "0.1.0"},
        }
    elif method == "tools/list":
        try:
            result = {"tools": hub.list_tools()}
        except HubClientError as error:
            return _error_response(request_id, -32000, f"{error.code}: {error}")
    elif method == "tools/call":
        parameters = body.get("params") if isinstance(body.get("params"), dict) else {}
        name = str(parameters.get("name", ""))
        arguments = parameters.get("arguments") if isinstance(parameters.get("arguments"), dict) else {}
        try:
            text = hub.call(route, name, arguments)
            result = {
                "content": [{"type": "text", "text": text}],
                "isError": text.startswith("[FAIL]"),
            }
        except HubClientError as error:
            result = {
                "content": [{"type": "text", "text": f"{error.code}: {error}"}],
                "isError": True,
            }
    else:
        return _error_response(request_id, -32601, "Method not found")
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


@router.post("/api/hub/mcp/{route_id}")
def resident_hub_mcp(
    route_id: str,
    request: Request,
    body: dict,
    authorization: str | None = Header(default=None),
):
    return _mcp_response(request, body, authorization, route_id=route_id)
