from types import SimpleNamespace

from app.api import plugin_socket
from plugin_hub.client import HubClientError


class FakeClient:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error

    def status(self):
        if self.error is not None:
            raise self.error
        return self.result


def _phone_status():
    return {
        "online": True,
        "agent_version": "0.2.4",
        "pending_count": 1,
        "queued_count": 2,
    }


def test_status_uses_authenticated_authoritative_hub(monkeypatch):
    authenticated = []
    expected = {
        "online": True,
        "plugin_count": 13,
        "tool_count": 15,
        "failed_count": 0,
        "plugins": [],
    }
    monkeypatch.setattr(
        plugin_socket,
        "require_session",
        lambda request: authenticated.append(request),
    )
    monkeypatch.setattr(
        plugin_socket.HubClient,
        "from_manifest",
        lambda: FakeClient(result=expected),
    )
    monkeypatch.setattr(
        plugin_socket,
        "get_phone_relay_registry",
        lambda: SimpleNamespace(status=_phone_status),
    )
    request = SimpleNamespace()

    assert plugin_socket.plugin_socket_status(request) == {
        **expected,
        "phone_agent": _phone_status(),
    }
    assert authenticated == [request]


def test_offline_hub_returns_visible_status(monkeypatch):
    monkeypatch.setattr(
        plugin_socket,
        "require_session",
        lambda request: None,
    )
    monkeypatch.setattr(
        plugin_socket.HubClient,
        "from_manifest",
        lambda: FakeClient(
            error=HubClientError("HUB_OFFLINE", "pipe unavailable")
        ),
    )
    monkeypatch.setattr(
        plugin_socket,
        "get_phone_relay_registry",
        lambda: SimpleNamespace(status=_phone_status),
    )

    result = plugin_socket.plugin_socket_status(SimpleNamespace())

    assert result["online"] is False
    assert result["error"]["code"] == "HUB_OFFLINE"
    assert result["phone_agent"] == _phone_status()
