"""Patting-toy actions built on verified Tuya learning codes."""

from __future__ import annotations

import threading
import time
from typing import Callable

from .config import Settings
from .exceptions import (
    ToyCooldownError,
    ToyRoutineBusyError,
    ToyRoutineStepError,
    ToyRoutineTimeoutError,
    ToyServiceError,
)
from .tuya_client import TuyaClient


ClientFactory = Callable[[Settings], TuyaClient]


class ToyService:
    """Serialize physical commands and expose honest one-way results."""

    _CODE_FIELDS = {
        "power_toggle": "toy_power_code",
        "pat_toggle": "toy_pat_code",
        "speed_slower": "toy_slow_code",
        "speed_faster": "toy_fast_code",
    }

    def __init__(
        self,
        settings: Settings,
        client_factory: ClientFactory = TuyaClient,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._settings = settings
        self._client_factory = client_factory
        self._clock = clock
        self._sleep = sleeper
        self._command_lock = threading.Lock()
        self._routine_lock = threading.Lock()
        self._last_command_at: float | None = None

    def power_toggle(self) -> dict:
        return self._send("power_toggle")

    def pat_toggle(self) -> dict:
        return self._send("pat_toggle")

    def speed_slower(self) -> dict:
        return self._send("speed_slower")

    def speed_faster(self) -> dict:
        return self._send("speed_faster")

    def soothe_sleep(self, delay_after_power: int = 5) -> dict:
        if not 1 <= delay_after_power <= 15:
            raise ToyServiceError("delay_after_power must be between 1 and 15")
        if not self._routine_lock.acquire(blocking=False):
            raise ToyRoutineBusyError("A soothe_sleep routine is already running")

        started_at = self._clock()
        completed_steps: list[str] = []
        try:
            self._send("power_toggle", wait_for_cooldown=True)
            completed_steps.append("power_toggle")
            self._sleep(delay_after_power)
            self._check_routine_deadline(started_at)

            self._send("pat_toggle", wait_for_cooldown=True)
            completed_steps.append("pat_toggle")
            self._sleep(1)
            self._check_routine_deadline(started_at)

            self._send("speed_slower", wait_for_cooldown=True)
            completed_steps.append("speed_slower")
        except Exception as exc:
            if isinstance(exc, ToyRoutineStepError):
                raise
            raise ToyRoutineStepError(completed_steps, exc) from exc
        finally:
            self._routine_lock.release()

        return {
            "ok": True,
            "status": "routine_completed",
            "action": "soothe_sleep",
            "completed_steps": completed_steps,
            "warning": "Infrared is one-way; physical state is not confirmed.",
        }

    def _send(self, action: str, wait_for_cooldown: bool = False) -> dict:
        field_name = self._CODE_FIELDS[action]
        code = getattr(self._settings, field_name)
        if not code:
            raise ToyServiceError(f"Learning code is not configured for {action}")

        with self._command_lock:
            remaining = self._cooldown_remaining()
            if remaining > 0 and wait_for_cooldown:
                self._sleep(remaining)
            elif remaining > 0:
                raise ToyCooldownError(
                    f"Command cooldown active for {remaining:.2f} seconds"
                )

            with self._client_factory(self._settings) as client:
                cloud_response = client.send_learning_code(code)
            self._last_command_at = self._clock()

        return {
            "ok": True,
            "status": "command_sent",
            "action": action,
            "cloud_success": cloud_response.get("success", True),
            "warning": "Infrared is one-way; physical state is not confirmed.",
        }

    def _cooldown_remaining(self) -> float:
        if self._last_command_at is None:
            return 0.0
        elapsed = self._clock() - self._last_command_at
        cooldown = float(self._settings.toy_command_cooldown_seconds)
        return max(0.0, cooldown - elapsed)

    def _check_routine_deadline(self, started_at: float) -> None:
        elapsed = self._clock() - started_at
        if elapsed > self._settings.toy_max_routine_seconds:
            raise ToyRoutineTimeoutError("soothe_sleep exceeded its time limit")
