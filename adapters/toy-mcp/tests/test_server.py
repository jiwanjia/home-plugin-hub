"""Protocol tests for the Home Hub stdio child."""

from __future__ import annotations

import json

from server import PattingToyRpc


class FakeService:
    def power_toggle(self):
        return {"ok": True, "action": "power_toggle"}


class FakeAirConditionerService:
    def temperature_up(self):
        return {
            "ok": True,
            "action": "temperature_up",
            "target_temperature_c": 25,
        }


def test_tools_list_exposes_nine_tools_without_loading_config():
    response = PattingToyRpc().respond(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    )
    names = [tool["name"] for tool in response["result"]["tools"]]
    assert names == [
        "toy_power_toggle",
        "toy_pat_toggle",
        "toy_speed_slower",
        "toy_speed_faster",
        "toy_soothe_sleep",
        "air_conditioner_power_on",
        "air_conditioner_power_off",
        "air_conditioner_temperature_up",
        "air_conditioner_temperature_down",
    ]


def test_tool_call_returns_json_content():
    rpc = PattingToyRpc(service=FakeService())
    response = rpc.respond(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "toy_power_toggle", "arguments": {}},
        }
    )
    result = response["result"]
    payload = json.loads(result["content"][0]["text"])
    assert result["isError"] is False
    assert payload == {"ok": True, "action": "power_toggle"}


def test_air_conditioner_tool_uses_its_own_service():
    rpc = PattingToyRpc(
        service=FakeService(),
        air_conditioner_service=FakeAirConditionerService(),
    )
    response = rpc.respond(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "air_conditioner_temperature_up",
                "arguments": {},
            },
        }
    )

    result = response["result"]
    payload = json.loads(result["content"][0]["text"])
    assert result["isError"] is False
    assert payload["target_temperature_c"] == 25
