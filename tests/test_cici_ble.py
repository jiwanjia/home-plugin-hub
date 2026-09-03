"""Offline tests for verified Cici BLE profiles and btsnoop parsing."""

from __future__ import annotations

import json
import struct

import pytest

from mcp_plugins.cici_ble_protocol import CiciBleProfile, ProtocolProfileError
from mcp_plugins.cici_ble_trace import BTSNOOP_MAGIC, parse_att_writes
from mcp_plugins.cici_toy import CiciToyPlugin


class FakeCiciSession:
    def __init__(self):
        self.applied = []
        self.ramps = []
        self.stop_result = False
        self.closed = False

    def apply(self, profile, payload, duration_seconds):
        self.applied.append((profile, payload, duration_seconds))

    def ramp(self, profile, payloads, step_seconds):
        self.ramps.append((profile, payloads, step_seconds))

    def stop(self, profile):
        del profile
        return self.stop_result

    def close(self):
        self.closed = True


def _write_profile(tmp_path, **overrides):
    profile = {
        "version": 1,
        "verified": True,
        "device_name": "Cici+ 2",
        "service_uuid": "0000ffe0-0000-1000-8000-00805f9b34fb",
        "write_characteristic": "0000ffe1-0000-1000-8000-00805f9b34fb",
        "notify_characteristic": "0000ffe2-0000-1000-8000-00805f9b34fb",
        "write_with_response": True,
        "notification_timeout_seconds": 0.1,
        "commands": {
            "start": "55 03 00 00 01 01 00",
            "stop": "55 03 00 00 00 00 00",
        },
        "intensities": {
            "1": "55 03 00 00 01 01 00",
            "2": "55 03 00 00 01 02 00",
            "3": "55 03 00 00 01 03 00",
            "4": "55 03 00 00 01 04 00",
            "5": "55 03 00 00 01 05 00",
            "6": "55 03 00 00 01 06 00",
            "7": "55 03 00 00 01 07 00",
            "8": "55 03 00 00 01 08 00",
            "9": "55 03 00 00 01 09 00",
            "10": "55 03 00 00 01 0A 00",
        },
        "patterns": {
            "1": "55 03 00 00 01 03 00",
            "2": "55 03 00 00 02 03 00",
            "3": "55 03 00 00 03 03 00",
            "4": "55 03 00 00 04 03 00",
            "5": "55 03 00 00 05 03 00",
        },
    }
    profile.update(overrides)
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(profile), encoding="utf-8")
    return path


def test_profile_resolves_only_captured_commands(tmp_path):
    profile = CiciBleProfile.load(_write_profile(tmp_path))
    assert profile.resolve_command("start", None) == bytes.fromhex(
        "55 03 00 00 01 01 00"
    )
    assert profile.resolve_command("intensity", 2) == bytes.fromhex(
        "55 03 00 00 01 02 00"
    )
    with pytest.raises(ProtocolProfileError, match="Uncaptured intensity"):
        profile.resolve_command("intensity", 11)


def test_profile_rejects_unverified_data(tmp_path):
    path = _write_profile(tmp_path, verified=False)
    with pytest.raises(ProtocolProfileError, match="not marked"):
        CiciBleProfile.load(path)


def test_profile_requires_notification_characteristic(tmp_path):
    path = _write_profile(tmp_path, notify_characteristic=None)
    with pytest.raises(ProtocolProfileError, match="notify_characteristic"):
        CiciBleProfile.load(path)


def test_profile_composes_verified_mode_and_intensity(tmp_path):
    profile = CiciBleProfile.load(_write_profile(tmp_path))

    payload = profile.resolve_vibration(mode=5, intensity=10)

    assert payload == bytes.fromhex("55 03 00 00 05 0A 00")


def test_profile_rejects_unverified_vibration_dimension(tmp_path):
    profile = CiciBleProfile.load(_write_profile(tmp_path))

    with pytest.raises(ProtocolProfileError, match="Uncaptured pattern"):
        profile.resolve_vibration(mode=6, intensity=1)
    with pytest.raises(ProtocolProfileError, match="Uncaptured intensity"):
        profile.resolve_vibration(mode=1, intensity=11)


def test_plugin_schedules_duration_after_written_command(monkeypatch, tmp_path):
    profile_path = _write_profile(tmp_path)
    session = FakeCiciSession()

    monkeypatch.setattr(
        CiciToyPlugin,
        "_profile_path",
        staticmethod(lambda: profile_path),
    )
    result = CiciToyPlugin(session).execute(
        action="intensity",
        value=2,
        duration_seconds=1.5,
    )

    assert result.ok is True
    _, payload, duration = session.applied[0]
    assert payload == bytes.fromhex("55 03 00 00 01 02 00")
    assert duration == 1.5
    assert "auto-stop scheduled after 1.5 seconds" in result.data


def test_plugin_rejects_duration_for_stop():
    result = CiciToyPlugin().execute(
        action="stop",
        duration_seconds=1,
    )

    assert result.ok is False
    assert "cannot be used with stop" in result.error


def test_plugin_sends_combined_vibration_command(monkeypatch, tmp_path):
    profile_path = _write_profile(tmp_path)
    session = FakeCiciSession()

    monkeypatch.setattr(
        CiciToyPlugin,
        "_profile_path",
        staticmethod(lambda: profile_path),
    )
    result = CiciToyPlugin(session).execute(
        action="vibrate",
        mode=4,
        intensity=8,
        duration_seconds=2,
    )

    assert result.ok is True
    _, payload, duration = session.applied[0]
    assert payload == bytes.fromhex("55 03 00 00 04 08 00")
    assert duration == 2.0


def test_plugin_ramps_through_all_verified_intensities(monkeypatch, tmp_path):
    profile_path = _write_profile(tmp_path)
    session = FakeCiciSession()

    monkeypatch.setattr(
        CiciToyPlugin,
        "_profile_path",
        staticmethod(lambda: profile_path),
    )
    result = CiciToyPlugin(session).execute(action="ramp")

    assert result.ok is True
    _, payloads, step_seconds = session.ramps[0]
    assert payloads == [
        bytes.fromhex(f"55 03 00 00 01 {level:02x} 00")
        for level in range(1, 11)
    ]
    assert step_seconds == 3.0
    assert "10 verified levels" in result.data


def test_plugin_stop_is_idempotent_and_close_releases_session(monkeypatch, tmp_path):
    profile_path = _write_profile(tmp_path)
    session = FakeCiciSession()
    monkeypatch.setattr(
        CiciToyPlugin,
        "_profile_path",
        staticmethod(lambda: profile_path),
    )

    plugin = CiciToyPlugin(session)
    result = plugin.execute(action="stop")
    plugin.close()

    assert result.ok is True
    assert "already stopped" in result.data
    assert session.closed is True


def test_btsnoop_extracts_host_att_write():
    att = b"\x52" + struct.pack("<H", 37) + b"\xAA\x10"
    l2cap = struct.pack("<HH", len(att), 4) + att
    acl = struct.pack("<HH", 1, len(l2cap)) + l2cap
    packet = b"\x02" + acl
    record = struct.pack(">IIIIQ", len(packet), len(packet), 0, 0, 123) + packet
    capture = BTSNOOP_MAGIC + struct.pack(">II", 1, 1002) + record

    writes = parse_att_writes(capture)

    assert len(writes) == 1
    assert writes[0].attribute_handle == 37
    assert writes[0].payload_hex == "aa10"


def test_btsnoop_ignores_controller_to_host_write_shape():
    att = b"\x52" + struct.pack("<H", 37) + b"\xAA"
    l2cap = struct.pack("<HH", len(att), 4) + att
    acl = struct.pack("<HH", 1, len(l2cap)) + l2cap
    packet = b"\x02" + acl
    record = struct.pack(">IIIIQ", len(packet), len(packet), 1, 0, 123) + packet
    capture = BTSNOOP_MAGIC + struct.pack(">II", 1, 1002) + record
    assert parse_att_writes(capture) == []
