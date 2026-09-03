"""Short-lived Windows Named Pipe client for the Home Plugin Hub."""

import json
from multiprocessing.connection import Client
from pathlib import Path
from typing import Any, Dict, List, Optional

from .manifest import load_manifest


HOME_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = HOME_ROOT / "config" / "plugins.yaml"


class HubClientError(RuntimeError):
    """Error returned by the Hub or raised while reaching it."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class HubClient:
    """Send one JSON request per local Named Pipe connection."""

    def __init__(self, pipe_name: str):
        self._pipe_name = pipe_name

    @classmethod
    def from_manifest(cls, manifest_path: Path = DEFAULT_MANIFEST):
        """Build a client from the single plugin manifest."""
        manifest = load_manifest(Path(manifest_path))
        return cls(manifest.pipe_name)

    def ping(self) -> bool:
        """Return False only when the local Hub cannot be reached."""
        try:
            response = self._request("ping")
        except HubClientError as exc:
            if exc.code == "HUB_OFFLINE":
                return False
            raise
        return response == {"online": True}

    def status(self) -> Dict[str, Any]:
        return self._request("status")

    def list_plugins(self) -> List[Dict[str, Any]]:
        return self._request("list_plugins")

    def list_tools(self) -> List[Dict[str, Any]]:
        return self._request("list_tools")

    def operation_log(self, limit: int = 20) -> Dict[str, Any]:
        return self._request("operation_log", {"limit": limit})

    def call_tool(
        self,
        name: str,
        arguments: Dict[str, Any],
        host_context: Optional[Dict[str, Any]] = None,
    ) -> str:
        payload = {
            "name": name,
            "arguments": arguments,
            "host_context": host_context or {},
        }
        return self._request("call_tool", payload)

    def call_tool_detailed(
        self,
        name: str,
        arguments: Dict[str, Any],
        host_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Call a tool while preserving its structured success state."""
        payload = {
            "name": name,
            "arguments": arguments,
            "host_context": host_context or {},
        }
        return self._request("call_tool_detailed", payload)

    def release_execution_scope(self, scope_id: str) -> None:
        self._request("release_execution_scope", {"scope_id": scope_id})

    def _request(
        self,
        operation: str,
        payload: Optional[Dict[str, Any]] = None,
    ):
        request = {
            "operation": operation,
            "payload": payload or {},
        }

        try:
            connection = Client(
                self._pipe_name,
                family="AF_PIPE",
                authkey=None,
            )
        except (FileNotFoundError, OSError) as exc:
            raise HubClientError(
                "HUB_OFFLINE",
                f"Home Plugin Hub 离线: {exc}",
            ) from exc

        try:
            encoded_request = json.dumps(
                request,
                ensure_ascii=False,
            ).encode("utf-8")
            connection.send_bytes(encoded_request)
            encoded_response = connection.recv_bytes()
        except (EOFError, OSError) as exc:
            raise HubClientError(
                "HUB_OFFLINE",
                f"Home Plugin Hub 连接中断: {exc}",
            ) from exc
        finally:
            connection.close()

        try:
            response = json.loads(encoded_response.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HubClientError(
                "BAD_RESPONSE",
                f"Home Plugin Hub 返回了无效响应: {exc}",
            ) from exc

        if response.get("ok") is True:
            return response.get("result")

        error = response.get("error", {})
        code = error.get("code", "TOOL_ERROR")
        message = error.get("message", "Home Plugin Hub 请求失败")
        raise HubClientError(code, message)
