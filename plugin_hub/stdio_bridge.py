"""Thin stdio MCP bridge to the sole local Home Plugin Hub process."""

import argparse
import json
import sys
from typing import Any, Dict, Optional

from .client import DEFAULT_MANIFEST, HubClient, HubClientError
from .manifest import load_manifest
from .residents import load_resident_registry
from .execution_scope_state import read_execution_scope


PROTOCOL_VERSION = "2025-06-18"


def _configure_protocol_streams() -> None:
    """Keep MCP JSON-RPC UTF-8 even under a Windows GBK console."""
    for stream in (sys.stdin, sys.stdout):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(
                encoding="utf-8",
                errors="strict",
            )


class StdioHubBridge:
    """Translate MCP stdio requests into local HubClient calls."""

    def __init__(
        self,
        client: HubClient,
        resident_id: str,
        memory_route: Optional[str] = None,
        resident_registry=None,
    ):
        registry = resident_registry or load_resident_registry()
        registry.resolve_memory_route(resident_id, memory_route)
        self._client = client
        self._host_context = {
            "client_id": resident_id,
            "memory_route": memory_route,
        }

    def respond(
        self,
        request: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        method = request.get("method")
        request_id = request.get("id")

        if method == "notifications/initialized":
            return None
        try:
            if method == "initialize":
                result = self._initialize_result()
            elif method == "tools/list":
                result = {"tools": self._list_tools()}
            elif method == "tools/call":
                result = self._call_tool(request)
            else:
                return self._error_response(
                    request_id,
                    -32601,
                    "Method not found",
                )
        except HubClientError as exc:
            return self._error_response(
                request_id,
                -32000,
                f"{exc.code}: {exc}",
            )

        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": result,
        }

    def _initialize_result(self) -> Dict[str, Any]:
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {
                "name": "home-plugin-hub",
                "version": "0.1.0",
            },
        }

    def _list_tools(self):
        hub_tools = self._client.list_tools()
        return [
            {
                "name": tool["function"]["name"],
                "description": tool["function"]["description"],
                "inputSchema": tool["function"]["parameters"],
            }
            for tool in hub_tools
        ]

    def _call_tool(self, request: Dict[str, Any]) -> Dict[str, Any]:
        params = request.get("params")
        if not isinstance(params, dict):
            return self._tool_error("tools/call params 必须是对象")

        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str) or not name:
            return self._tool_error("tools/call name 必须是非空字符串")
        if not isinstance(arguments, dict):
            return self._tool_error("tools/call arguments 必须是对象")

        try:
            host_context = dict(self._host_context)
            execution_scope_id = read_execution_scope()
            if execution_scope_id:
                host_context["execution_scope_id"] = execution_scope_id
            text = self._client.call_tool(
                name,
                arguments,
                host_context=host_context,
            )
        except HubClientError as exc:
            return self._tool_error(f"{exc.code}: {exc}")

        return {
            "content": [{"type": "text", "text": text}],
            "isError": text.startswith("[FAIL]"),
        }

    @staticmethod
    def _tool_error(message: str) -> Dict[str, Any]:
        return {
            "content": [{"type": "text", "text": message}],
            "isError": True,
        }

    @staticmethod
    def _error_response(
        request_id: Any,
        code: int,
        message: str,
    ) -> Dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": code,
                "message": message,
            },
        }


def _build_parser() -> argparse.ArgumentParser:
    resident_ids = load_resident_registry().ids
    parser = argparse.ArgumentParser(
        description="Forward one Home resident's MCP calls to Plugin Hub",
    )
    parser.add_argument(
        "--client",
        required=True,
        choices=resident_ids,
        help="Fixed Home resident identity injected by the host",
    )
    parser.add_argument(
        "--memory-route",
        help="Existing memory source owned by the chosen identity",
    )
    parser.add_argument(
        "--pipe",
        default=load_manifest(DEFAULT_MANIFEST).pipe_name,
        help="Home Plugin Hub Named Pipe",
    )
    return parser


def main() -> int:
    _configure_protocol_streams()
    args = _build_parser().parse_args()
    bridge = StdioHubBridge(
        HubClient(args.pipe),
        args.client,
        args.memory_route,
    )

    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
            response = bridge.respond(request)
        except Exception as exc:
            response = StdioHubBridge._error_response(
                None,
                -32603,
                str(exc),
            )
        if response is not None:
            print(
                json.dumps(response, ensure_ascii=False),
                flush=True,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
