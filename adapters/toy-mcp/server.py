"""stdio MCP entrypoint for the patting toy managed by Home Plugin Hub."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from app.air_conditioner_service import AirConditionerService
from app.config import load_settings
from app.exceptions import ToyMCPError, ToyRoutineStepError
from app.toy_service import ToyService


TOOLS = [
    {
        "name": "toy_power_toggle",
        "description": "Send the patting toy's one-way infrared power toggle.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "toy_pat_toggle",
        "description": "Send the patting on/off toggle learned by the Tuya remote.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "toy_speed_slower",
        "description": "Decrease the patting speed by one remote-control step.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "toy_speed_faster",
        "description": "Increase the patting speed by one remote-control step.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "toy_soothe_sleep",
        "description": "Send power, patting and slower commands in a finite routine.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "delay_after_power": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 15,
                    "default": 5,
                }
            },
        },
    },
    {
        "name": "air_conditioner_power_on",
        "description": "Turn on the bound Tuya infrared air conditioner.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "air_conditioner_power_off",
        "description": "Turn off the bound Tuya infrared air conditioner.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "air_conditioner_temperature_up",
        "description": "Raise the bound air conditioner's target by 1 degree Celsius.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "air_conditioner_temperature_down",
        "description": "Lower the bound air conditioner's target by 1 degree Celsius.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


class PattingToyRpc:
    """Route MCP calls to persistent toy and air-conditioner services."""

    def __init__(
        self,
        service: ToyService | None = None,
        air_conditioner_service: AirConditionerService | None = None,
    ) -> None:
        self._service = service
        self._air_conditioner_service = air_conditioner_service

    def respond(self, request: dict[str, Any]) -> dict[str, Any] | None:
        request_id = request.get("id")
        if request_id is None:
            return None
        method = request.get("method")
        if method == "initialize":
            result = {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "patting-toy", "version": "1"},
            }
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            result = self._call_tool(request.get("params", {}))
        else:
            return self._error(request_id, f"Unknown method: {method}")
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def _call_tool(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments", {})
        try:
            if name == "toy_power_toggle":
                payload = self._get_service().power_toggle()
            elif name == "toy_pat_toggle":
                payload = self._get_service().pat_toggle()
            elif name == "toy_speed_slower":
                payload = self._get_service().speed_slower()
            elif name == "toy_speed_faster":
                payload = self._get_service().speed_faster()
            elif name == "toy_soothe_sleep":
                delay = arguments.get("delay_after_power", 5)
                payload = self._get_service().soothe_sleep(
                    delay_after_power=delay
                )
            elif name == "air_conditioner_power_on":
                payload = self._get_air_conditioner_service().power_on()
            elif name == "air_conditioner_power_off":
                payload = self._get_air_conditioner_service().power_off()
            elif name == "air_conditioner_temperature_up":
                payload = self._get_air_conditioner_service().temperature_up()
            elif name == "air_conditioner_temperature_down":
                payload = self._get_air_conditioner_service().temperature_down()
            else:
                return self._tool_error(f"Unknown tool: {name}")
        except ToyRoutineStepError as exc:
            payload = {
                "ok": False,
                "error": str(exc.cause),
                "completed_steps": exc.completed_steps,
            }
            return self._tool_payload(payload, is_error=True)
        except ToyMCPError as exc:
            return self._tool_error(str(exc))
        except Exception as exc:
            return self._tool_error(f"Unexpected patting-toy error: {exc}")
        return self._tool_payload(payload, is_error=False)

    def _get_service(self) -> ToyService:
        if self._service is None:
            env_path = Path(__file__).resolve().parent / ".env"
            settings = load_settings(env_file=env_path)
            self._service = ToyService(settings)
        return self._service

    def _get_air_conditioner_service(self) -> AirConditionerService:
        if self._air_conditioner_service is None:
            env_path = Path(__file__).resolve().parent / ".env"
            settings = load_settings(env_file=env_path)
            self._air_conditioner_service = AirConditionerService(settings)
        return self._air_conditioner_service

    @staticmethod
    def _tool_payload(payload: dict, is_error: bool) -> dict:
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        return {
            "content": [{"type": "text", "text": text}],
            "isError": is_error,
        }

    def _tool_error(self, message: str) -> dict:
        return self._tool_payload({"ok": False, "error": message}, True)

    @staticmethod
    def _error(request_id: Any, message: str) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": message},
        }


def main() -> int:
    rpc = PattingToyRpc()
    for line in sys.stdin:
        try:
            request = json.loads(line)
            response = rpc.respond(request)
        except Exception as exc:
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32603, "message": str(exc)},
            }
        if response is not None:
            print(json.dumps(response, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
