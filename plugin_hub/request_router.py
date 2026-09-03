"""Validate Named Pipe requests and route them through the Hub core."""

import json
from typing import Any, Dict

from .core import HubError, PluginHub, ToolNotFoundError


class HubRequestRouter:
    """Translate JSON request envelopes into PluginHub method calls."""

    def __init__(self, hub: PluginHub, pipe_name: str):
        self._hub = hub
        self._pipe_name = pipe_name

    def dispatch_encoded(self, raw_request: bytes) -> bytes:
        try:
            request = json.loads(raw_request.decode("utf-8"))
            result = self._dispatch(request)
            response = {
                "ok": True,
                "result": result,
            }
        except Exception as exc:
            response = {
                "ok": False,
                "error": self._error_payload(exc),
            }

        return json.dumps(
            response,
            ensure_ascii=False,
        ).encode("utf-8")

    def _dispatch(self, request: Dict[str, Any]):
        if not isinstance(request, dict):
            raise HubError("请求必须是对象")

        operation = request.get("operation")
        payload = request.get("payload", {})
        if not isinstance(payload, dict):
            raise HubError("payload 必须是对象")

        if operation == "ping":
            return {"online": True}
        if operation == "status":
            return self._service_status()
        if operation == "list_plugins":
            return self._hub.list_plugins()
        if operation == "list_tools":
            return self._hub.list_tools()
        if operation == "operation_log":
            return self._operation_log(payload)
        if operation == "call_tool":
            return self._call_tool(payload)
        if operation == "call_tool_detailed":
            return self._call_tool_detailed(payload)
        if operation == "release_execution_scope":
            return self._release_execution_scope(payload)
        raise HubError(f"未知操作: {operation!r}")

    def _operation_log(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        limit = payload.get("limit", 20)
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise HubError("operation_log.limit 必须是整数")
        operations = self._hub.get_operation_log(limit)
        return {
            "count": len(operations),
            "operations": operations,
            "session_summary": self._hub.get_operation_summary(),
        }

    def _service_status(self) -> Dict[str, Any]:
        status = self._hub.status()
        status["transport"] = "named_pipe"
        status["pipe_name"] = self._pipe_name
        return status

    def _call_tool(self, payload: Dict[str, Any]) -> str:
        name, arguments, host_context = self._validated_call(payload)
        return self._hub.call_tool(
            name,
            arguments,
            host_context=host_context,
        )

    def _call_tool_detailed(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        name, arguments, host_context = self._validated_call(payload)
        result = self._hub.call_tool_result(
            name,
            arguments,
            host_context=host_context,
        )
        return {
            "ok": result.ok,
            "operation": result.operation,
            "path": result.path,
            "error": result.error,
            "message": result.to_message(),
        }

    def _release_execution_scope(self, payload: Dict[str, Any]):
        scope_id = payload.get("scope_id")
        self._hub.release_execution_scope(scope_id)
        return {"released": True}

    @staticmethod
    def _validated_call(payload: Dict[str, Any]):
        name = payload.get("name")
        arguments = payload.get("arguments")
        host_context = payload.get("host_context", {})

        if not isinstance(name, str) or not name:
            raise HubError("call_tool.name 必须是非空字符串")
        if not isinstance(arguments, dict):
            raise HubError("call_tool.arguments 必须是对象")
        if not isinstance(host_context, dict):
            raise HubError("call_tool.host_context 必须是对象")

        return name, arguments, host_context

    def _error_payload(self, exc: Exception) -> Dict[str, str]:
        if isinstance(exc, ToolNotFoundError):
            code = "TOOL_NOT_FOUND"
        elif isinstance(exc, HubError):
            code = "BAD_REQUEST"
        elif isinstance(exc, (UnicodeDecodeError, json.JSONDecodeError)):
            code = "BAD_REQUEST"
        else:
            code = "TOOL_ERROR"
        return {
            "code": code,
            "message": str(exc),
        }
