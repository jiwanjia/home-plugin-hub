"""Acceptance tests for the Home Plugin Hub remote MCP door.

The door must expose the Hub catalog verbatim, reuse the existing owner
authorization server, and keep resident identity server-selected.
"""

from fastapi.testclient import TestClient

from app.handoff.oauth_store import OAuthGrant
from app.hub.mcp_service import HubMcpService
from app.main import create_app
from app.memory_capture.oauth import OFFLINE_SCOPE, READ_SCOPE, WRITE_SCOPE
from plugin_hub.client import HubClient
from plugin_hub.residents import load_resident_registry
from tests.integration.test_memory_capture_mcp import capture_settings


def first_route_id(client) -> str:
    return client.app.state.hub_mcp.registry.mcp_route_ids[0]


def issue_hub_token(client, route_id, scope=f"{READ_SCOPE} {WRITE_SCOPE} {OFFLINE_SCOPE}"):
    resource = f"http://testserver/api/hub/mcp/{route_id}"
    grant = OAuthGrant(1, "hub-test", resource, scope, "hub-family")
    token, _ = client.app.state.memory_oauth.issue_tokens(
        grant,
        access_ttl_seconds=600,
        refresh_ttl_seconds=600,
        include_refresh_token=False,
    )
    return token


def issue_memory_token(client, route_id):
    resource = f"http://testserver/api/memory/mcp/{route_id}"
    grant = OAuthGrant(1, "memory-test", resource, f"{READ_SCOPE} {WRITE_SCOPE} {OFFLINE_SCOPE}", "memory-family")
    token, _ = client.app.state.memory_oauth.issue_tokens(
        grant,
        access_ttl_seconds=600,
        refresh_ttl_seconds=600,
        include_refresh_token=False,
    )
    return token


def hub_request(client, route_id, method, token=None, params=None):
    body = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        body["params"] = params
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.post(f"/api/hub/mcp/{route_id}", headers=headers, json=body)


def test_hub_door_requires_its_own_token(tmp_path):
    with TestClient(create_app(capture_settings(tmp_path))) as client:
        assert client.app.state.hub_mcp is not None
        route_id = first_route_id(client)
        response = hub_request(client, route_id, "tools/list")
        assert response.status_code == 401
        challenge = response.headers.get("www-authenticate", "")
        assert f"/.well-known/oauth-protected-resource/api/hub/mcp/{route_id}" in challenge


def test_hub_protected_resource_metadata_reuses_memory_issuer(tmp_path):
    with TestClient(create_app(capture_settings(tmp_path))) as client:
        route_id = first_route_id(client)
        response = client.get(f"/.well-known/oauth-protected-resource/api/hub/mcp/{route_id}")
        assert response.status_code == 200
        metadata = response.json()
        assert metadata["resource"] == f"http://testserver/api/hub/mcp/{route_id}"
        assert metadata["authorization_servers"] == ["http://testserver/api/memory/oauth"]
        assert metadata["bearer_methods_supported"] == ["header"]


def test_hub_lists_every_tool_from_the_live_catalog(tmp_path):
    with TestClient(create_app(capture_settings(tmp_path))) as client:
        route_id = first_route_id(client)
        token = issue_hub_token(client, route_id)
        response = hub_request(client, route_id, "tools/list", token=token)
        assert response.status_code == 200
        tools = response.json()["result"]["tools"]
        expected = HubClient.from_manifest().list_tools()
        assert [tool["name"] for tool in tools] == [
            tool["function"]["name"] for tool in expected
        ]
        assert tools, "the Hub catalog must not be empty"


def test_a_memory_token_cannot_open_the_hub(tmp_path):
    with TestClient(create_app(capture_settings(tmp_path))) as client:
        route_id = first_route_id(client)
        response = hub_request(client, route_id, "tools/list", token=issue_memory_token(client, route_id))
        assert response.status_code == 401


def test_a_hub_token_cannot_open_memory(tmp_path):
    with TestClient(create_app(capture_settings(tmp_path))) as client:
        route_id = first_route_id(client)
        response = client.post(
            f"/api/memory/mcp/{route_id}",
            headers={"Authorization": f"Bearer {issue_hub_token(client, route_id)}"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert response.status_code == 401


def test_hub_route_identity_is_server_selected(tmp_path):
    seen = {}

    class RecordingClient:
        def list_tools(self):
            return []

        def call_tool(self, name, arguments, host_context=None):
            seen.update(host_context or {})
            return "ok"

    registry = load_resident_registry()
    service = HubMcpService(registry=registry, client=RecordingClient())
    route = service.resolve_route(registry.mcp_route_ids[0])
    service.call(route, "hub_status", {"client_id": "caller-supplied"})
    assert seen["client_id"] == route.resident_id
    assert seen["memory_route"] == route.write_route.id
