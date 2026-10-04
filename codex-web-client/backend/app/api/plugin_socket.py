"""Authenticated read-only view of the Home Plugin Hub catalog."""

from fastapi import APIRouter, Request

from app.api.threads import require_session
from phone_relay.registry import get_phone_relay_registry
from plugin_hub.client import HubClient, HubClientError


router = APIRouter(prefix="/api/plugin-socket")


@router.get("")
def plugin_socket_status(request: Request) -> dict:
    """Return the running Hub's authoritative status without loading plugins."""
    require_session(request)
    client = HubClient.from_manifest()
    try:
        hub_status = client.status()
    except HubClientError as exc:
        hub_status = {
            "online": False,
            "plugin_count": 0,
            "tool_count": 0,
            "failed_count": 0,
            "plugins": [],
            "error": {
                "code": exc.code,
                "message": str(exc),
            },
        }
    return {
        **hub_status,
        "phone_agent": get_phone_relay_registry().status(),
    }
