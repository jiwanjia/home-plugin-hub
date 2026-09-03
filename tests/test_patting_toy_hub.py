"""Verify that the patting toy is a child of the existing Home Hub."""

from __future__ import annotations

from pathlib import Path

from plugin_hub.core import PluginHub


HOME_ROOT = Path(__file__).resolve().parents[1]
TOY_PYTHON = HOME_ROOT / "adapters" / "toy-mcp" / "venv" / "Scripts" / "python.exe"
TOY_SERVER = HOME_ROOT / "adapters" / "toy-mcp" / "server.py"


def test_patting_toy_stdio_tools_join_one_hub(tmp_path):
    manifest = tmp_path / "plugins.yaml"
    manifest.write_text(
        "\n".join(
            [
                "version: 1",
                r"pipe_name: \\.\pipe\patting-toy-test",
                "plugins:",
                "  - id: patting_toy",
                "    kind: mcp_stdio",
                f'    command: "{TOY_PYTHON.as_posix()}"',
                "    args:",
                f'      - "{TOY_SERVER.as_posix()}"',
                "    enabled: true",
            ]
        ),
        encoding="utf-8",
    )
    hub = PluginHub(manifest)
    try:
        hub.start()
        names = [tool["function"]["name"] for tool in hub.list_tools()]
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
        assert hub.status()["failed_count"] == 0
    finally:
        hub.close()
