from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request


@dataclass(frozen=True)
class HubOAuthUrls:
    issuer: str
    resource: str
    protected_resource_metadata: str


def hub_oauth_urls(
    request: Request,
    route_id: str | None = None,
) -> HubOAuthUrls:
    """Hub MCP resource URLs.

    The authorization server deliberately stays the existing Memory OAuth
    issuer: one owner password box, one consent screen, no second issuer and
    no second token store. Tokens are separated by their ``resource`` value,
    so a Memory token can never authorize a Hub call.
    """
    forwarded_host = request.headers.get("x-forwarded-host", "").split(",", 1)[0].strip()
    if forwarded_host:
        forwarded_scheme = request.headers.get("x-forwarded-proto", "https").split(",", 1)[0]
        scheme = "https" if forwarded_scheme.lower() == "https" else "http"
        origin = f"{scheme}://{forwarded_host}".rstrip("/")
    else:
        origin = str(request.base_url).rstrip("/")
    suffix = f"/{route_id}" if route_id else ""
    return HubOAuthUrls(
        issuer=f"{origin}/api/memory/oauth",
        resource=f"{origin}/api/hub/mcp{suffix}",
        protected_resource_metadata=(
            f"{origin}/.well-known/oauth-protected-resource/api/hub/mcp{suffix}"
        ),
    )
