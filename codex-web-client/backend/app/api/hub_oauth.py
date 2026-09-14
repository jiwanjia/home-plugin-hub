"""Protected-resource metadata for the Home Plugin Hub MCP endpoint.

Only discovery metadata is added here. The authorization server, the consent
page, and the token store are the existing Memory OAuth ones, so no new
outward page appears.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.hub.oauth import hub_oauth_urls
from app.memory_capture.oauth import OFFLINE_SCOPE, READ_SCOPE, WRITE_SCOPE


metadata_router = APIRouter()


@metadata_router.get("/.well-known/oauth-protected-resource/api/hub/mcp/{route_id}")
def hub_protected_resource_metadata(route_id: str, request: Request):
    try:
        request.app.state.hub_mcp.resolve_route(route_id)
    except (AttributeError, ValueError) as error:
        return JSONResponse(
            {"error": "invalid_target", "error_description": str(error)},
            status_code=404,
        )
    urls = hub_oauth_urls(request, route_id)
    return {
        "resource": urls.resource,
        "authorization_servers": [urls.issuer],
        "scopes_supported": [READ_SCOPE, WRITE_SCOPE, OFFLINE_SCOPE],
        "bearer_methods_supported": ["header"],
        "resource_name": f"Home Plugin Hub ({route_id})",
    }
