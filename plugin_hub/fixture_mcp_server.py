"""No-side-effect MCP fixture used to verify the unified socket."""

from __future__ import annotations

import json
import sys
from typing import Any, Dict


TOOL = {
    "name": "home_fixture_echo",
    "description": "Return fixture text without external side effects.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Text returned by the fixture.",
            }
        },
        "required": ["text"],
    },
}


def respond(request: Dict[str, Any]) -> Dict[str, Any] | None:
    request_id = request.get("id")
    method = request.get("method")
    if request_id is None:
        return None
    if method == "initialize":
        result = {
            "protocolVersion": "2025-03-26",
            "capabilities": {"tools": {}},
            "serverInfo": {
                "name": "home-fixture",
                "version": "1",
            },
        }
    elif method == "tools/list":
        result = {"tools": [TOOL]}
    elif method == "tools/call":
        params = request.get("params", {})
        arguments = params.get("arguments", {})
        text = arguments.get("text", "")
        result = {
            "content": [{"type": "text", "text": str(text)}],
            "isError": False,
        }
    else:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": -32601,
                "message": f"Unknown method: {method}",
            },
        }
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": result,
    }


def main() -> int:
    for line in sys.stdin:
        try:
            request = json.loads(line)
            response = respond(request)
        except Exception as exc:
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32603, "message": str(exc)},
            }
        if response is not None:
            print(
                json.dumps(response, ensure_ascii=False),
                flush=True,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
