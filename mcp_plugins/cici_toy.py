"""Home Hub plugin for protocol-verified Windows BLE control of Cici."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from core.tool_base import MCPlugin, ToolResult

from .cici_ble_protocol import CiciBleProfile, ProtocolProfileError
from .cici_ble_session import CiciBleSession


logger = logging.getLogger(__name__)
MAX_DURATION_SECONDS = 30.0
DEFAULT_RAMP_STEP_SECONDS = 3.0
DEFAULT_PROFILE_PATH = (
    Path(__file__).resolve().parent.parent
    / "config"
    / "cici_ble_protocol.json"
)


class CiciToyPlugin(MCPlugin):
    """Control Cici through a locally verified BLE command profile."""

    def __init__(self, session: CiciBleSession | None = None) -> None:
        self._session = session or CiciBleSession()

    @property
    def name(self) -> str:
        return "cici_toy"

    @property
    def description(self) -> str:
        return (
            "Control Cici directly through the Windows Bluetooth adapter. "
            "Only commands confirmed by a device capture are sent, and a successful "
            "GATT write keeps the reusable BLE session active. "
            "The SVA app must disconnect from the toy before Windows can connect."
        )

    @property
    def parameters(self) -> dict:
        return {
            "action": {
                "type": "string",
                "description": "Verified BLE action to execute.",
                "enum": [
                    "start",
                    "stop",
                    "intensity",
                    "pattern",
                    "ramp",
                    "vibrate",
                ],
            },
            "value": {
                "type": "integer",
                "description": (
                    "Captured intensity value or pattern number. "
                    "Required for intensity and pattern."
                ),
                "minimum": 1,
                "maximum": 10,
            },
            "mode": {
                "type": "integer",
                "description": "Verified vibration mode for the vibrate action.",
                "minimum": 1,
                "maximum": 5,
            },
            "intensity": {
                "type": "integer",
                "description": "Verified intensity for the vibrate action.",
                "minimum": 1,
                "maximum": 10,
            },
            "duration_seconds": {
                "type": "number",
                "description": (
                    "Optional duration for start, intensity, or pattern. "
                    "For ramp, this is the time per verified intensity level "
                    "and defaults to 3 seconds. Timed work continues in the "
                    "background and can be interrupted by stop."
                ),
                "minimum": 0.1,
                "maximum": MAX_DURATION_SECONDS,
            },
        }

    def execute(
        self,
        action: str = "stop",
        value: int | None = None,
        duration_seconds: float | None = None,
        mode: int | None = None,
        intensity: int | None = None,
    ) -> ToolResult:
        try:
            duration = self._validated_duration(action, duration_seconds)
            profile = CiciBleProfile.load(self._profile_path())
            if action == "stop":
                was_running = self._session.stop(profile)
                if was_running:
                    message = "Cici verified stop written; session closed"
                else:
                    message = "Cici is already stopped"
                return ToolResult.success(message, operation="cici_toy")
            if action == "ramp":
                ramp_payloads = [
                    profile.intensities[level]
                    for level in sorted(profile.intensities)
                ]
                if not ramp_payloads:
                    raise ProtocolProfileError(
                        "No verified Cici intensity levels are available"
                    )
                self._session.ramp(
                    profile,
                    ramp_payloads,
                    duration,
                )
                levels = len(ramp_payloads)
                return ToolResult.success(
                    "Cici ramp first level written; "
                    f"{levels} verified levels scheduled for "
                    f"{duration:g} seconds each",
                    operation="cici_toy",
                )
            if action == "vibrate":
                if mode is None or intensity is None:
                    raise ProtocolProfileError(
                        "vibrate requires mode and intensity"
                    )
                payload = profile.resolve_vibration(mode, intensity)
            else:
                payload = profile.resolve_command(action, value)
            self._session.apply(profile, payload, duration)
        except FileNotFoundError:
            return ToolResult.fail(
                "Cici verified BLE profile has not been installed yet.",
                operation="cici_toy",
            )
        except ProtocolProfileError as exc:
            return ToolResult.fail(str(exc), operation="cici_toy")
        except ImportError:
            return ToolResult.fail(
                "The Home Hub Python environment does not provide bleak.",
                operation="cici_toy",
            )
        except Exception as exc:
            logger.exception("Cici BLE command failed")
            return ToolResult.fail(
                f"Cici BLE command failed: {exc}",
                operation="cici_toy",
            )
        message = f"Cici verified BLE action written: {action}"
        if duration is not None:
            message += f"; auto-stop scheduled after {duration:g} seconds"
        else:
            message += "; continuing until stopped or replaced"
        return ToolResult.success(message, operation="cici_toy")

    def close(self) -> None:
        self._session.close()

    @staticmethod
    def _validated_duration(
        action: str,
        duration_seconds: float | None,
    ) -> float | None:
        if duration_seconds is None:
            if action == "ramp":
                return DEFAULT_RAMP_STEP_SECONDS
            return None
        if action == "stop":
            raise ProtocolProfileError(
                "duration_seconds cannot be used with stop"
            )
        if isinstance(duration_seconds, bool) or not isinstance(
            duration_seconds,
            (int, float),
        ):
            raise ProtocolProfileError("duration_seconds must be a number")

        duration = float(duration_seconds)
        if not 0.1 <= duration <= MAX_DURATION_SECONDS:
            raise ProtocolProfileError(
                "duration_seconds must be between 0.1 and 30"
            )
        return duration

    @staticmethod
    def _profile_path() -> Path:
        configured = os.environ.get("CICI_BLE_PROFILE", "").strip()
        if configured:
            return Path(configured)
        return DEFAULT_PROFILE_PATH
