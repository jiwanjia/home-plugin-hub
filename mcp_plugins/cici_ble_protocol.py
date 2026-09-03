"""Load and validate Cici commands decoded from a real BLE capture."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ProtocolProfileError(ValueError):
    """Raised when a BLE profile is absent, unverified, or malformed."""


@dataclass(frozen=True)
class CiciBleProfile:
    device_name: str
    service_uuid: str
    write_characteristic: int | str
    notify_characteristic: int | str
    write_with_response: bool
    commands: dict[str, bytes]
    intensities: dict[int, bytes]
    patterns: dict[int, bytes]
    scan_timeout_seconds: float = 8.0
    connect_timeout_seconds: float = 10.0
    notification_timeout_seconds: float = 2.0

    @classmethod
    def load(cls, path: Path) -> "CiciBleProfile":
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ProtocolProfileError("Cici BLE profile must be a JSON object")
        if raw.get("version") != 1:
            raise ProtocolProfileError("Cici BLE profile version must be 1")
        if raw.get("verified") is not True:
            raise ProtocolProfileError(
                "Cici BLE profile is not marked as capture-verified"
            )

        device_name = cls._required_text(raw, "device_name")
        service_uuid = cls._optional_text(raw, "service_uuid")
        write_characteristic = cls._required_characteristic(
            raw,
            "write_characteristic",
        )
        notify_characteristic = cls._required_characteristic(
            raw,
            "notify_characteristic",
        )
        scan_timeout = cls._positive_number(
            raw,
            "scan_timeout_seconds",
            8,
        )
        connect_timeout = cls._positive_number(
            raw,
            "connect_timeout_seconds",
            10,
        )
        notification_timeout = cls._positive_number(
            raw,
            "notification_timeout_seconds",
            2,
        )

        commands = cls._payload_map(raw.get("commands"), {"start", "stop"})
        intensities = cls._numbered_payload_map(raw.get("intensities"))
        patterns = cls._numbered_payload_map(raw.get("patterns"))
        return cls(
            device_name=device_name,
            service_uuid=service_uuid,
            write_characteristic=write_characteristic,
            notify_characteristic=notify_characteristic,
            write_with_response=bool(raw.get("write_with_response", False)),
            commands=commands,
            intensities=intensities,
            patterns=patterns,
            scan_timeout_seconds=scan_timeout,
            connect_timeout_seconds=connect_timeout,
            notification_timeout_seconds=notification_timeout,
        )

    def resolve_command(self, action: str, value: int | None) -> bytes:
        if action in self.commands:
            return self.commands[action]
        if action == "intensity":
            return self._resolve_numbered("intensity", self.intensities, value)
        if action == "pattern":
            return self._resolve_numbered("pattern", self.patterns, value)
        raise ProtocolProfileError(f"Unsupported verified Cici action: {action}")

    def resolve_vibration(self, mode: int, intensity: int) -> bytes:
        pattern_payload = self._resolve_numbered(
            "pattern",
            self.patterns,
            mode,
        )
        intensity_payload = self._resolve_numbered(
            "intensity",
            self.intensities,
            intensity,
        )
        return self._compose_vibration_payload(
            pattern_payload,
            intensity_payload,
        )

    @staticmethod
    def _compose_vibration_payload(
        pattern_payload: bytes,
        intensity_payload: bytes,
    ) -> bytes:
        if len(pattern_payload) != 7 or len(intensity_payload) != 7:
            raise ProtocolProfileError(
                "Verified Cici vibration frames must contain 7 bytes"
            )
        if pattern_payload[:4] != intensity_payload[:4]:
            raise ProtocolProfileError(
                "Verified Cici vibration frames use different headers"
            )
        if pattern_payload[-1] != intensity_payload[-1]:
            raise ProtocolProfileError(
                "Verified Cici vibration frames use different tails"
            )

        payload = bytearray(pattern_payload)
        payload[5] = intensity_payload[5]
        return bytes(payload)

    @staticmethod
    def _resolve_numbered(
        label: str,
        choices: dict[int, bytes],
        value: int | None,
    ) -> bytes:
        if value is None:
            raise ProtocolProfileError(f"{label} requires value")
        if value not in choices:
            supported = ", ".join(str(item) for item in sorted(choices))
            raise ProtocolProfileError(
                f"Uncaptured {label} value {value}; available: {supported or 'none'}"
            )
        return choices[value]

    @classmethod
    def _payload_map(
        cls,
        value: Any,
        required: set[str],
    ) -> dict[str, bytes]:
        if not isinstance(value, dict):
            raise ProtocolProfileError("commands must be an object")
        missing = required.difference(value)
        if missing:
            names = ", ".join(sorted(missing))
            raise ProtocolProfileError(f"Missing verified commands: {names}")
        return {str(name): cls._hex_payload(payload) for name, payload in value.items()}

    @classmethod
    def _numbered_payload_map(cls, value: Any) -> dict[int, bytes]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ProtocolProfileError("Numbered commands must be an object")
        result = {}
        for number, payload in value.items():
            try:
                key = int(number)
            except (TypeError, ValueError) as exc:
                raise ProtocolProfileError(
                    f"Invalid numbered command key: {number!r}"
                ) from exc
            result[key] = cls._hex_payload(payload)
        return result

    @staticmethod
    def _hex_payload(value: Any) -> bytes:
        if not isinstance(value, str) or not value.strip():
            raise ProtocolProfileError("BLE payload must be non-empty hex text")
        compact = "".join(value.split())
        try:
            payload = bytes.fromhex(compact)
        except ValueError as exc:
            raise ProtocolProfileError("BLE payload contains invalid hex") from exc
        if not payload:
            raise ProtocolProfileError("BLE payload cannot be empty")
        return payload

    @staticmethod
    def _required_text(raw: dict, key: str) -> str:
        value = raw.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ProtocolProfileError(f"{key} must be non-empty text")
        return value.strip()

    @staticmethod
    def _optional_text(raw: dict, key: str) -> str:
        value = raw.get(key, "")
        if not isinstance(value, str):
            raise ProtocolProfileError(f"{key} must be text")
        return value.strip()

    @staticmethod
    def _required_characteristic(raw: dict, key: str) -> int | str:
        value = raw.get(key)
        if not isinstance(value, (int, str)) or value == "":
            raise ProtocolProfileError(
                f"{key} must be a GATT handle or UUID"
            )
        if isinstance(value, int) and value <= 0:
            raise ProtocolProfileError(f"{key} GATT handle must be positive")
        return value

    @staticmethod
    def _positive_number(raw: dict, key: str, default: float) -> float:
        value = raw.get(key, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ProtocolProfileError(f"{key} must be a positive number")
        parsed = float(value)
        if parsed <= 0:
            raise ProtocolProfileError(f"{key} must be a positive number")
        return parsed
