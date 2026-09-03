"""State-aware air-conditioner actions through one Tuya infrared hub."""

from __future__ import annotations

import threading
from typing import Callable

from .config import Settings
from .exceptions import AirConditionerServiceError
from .tuya_client import TuyaClient


AIR_CONDITIONER_CATEGORY_ID = 5
MINIMUM_TEMPERATURE_C = 16
MAXIMUM_TEMPERATURE_C = 30

ClientFactory = Callable[[Settings], TuyaClient]


class AirConditionerService:
    """Discover the single bound AC remote and expose explicit actions."""

    def __init__(
        self,
        settings: Settings,
        client_factory: ClientFactory = TuyaClient,
    ) -> None:
        self._settings = settings
        self._client_factory = client_factory
        self._command_lock = threading.Lock()
        self._remote_id: str | None = None

    def power_on(self) -> dict:
        return self._send_command("power_on", "power", 1)

    def power_off(self) -> dict:
        return self._send_command("power_off", "power", 0)

    def temperature_up(self) -> dict:
        return self._change_temperature(1)

    def temperature_down(self) -> dict:
        return self._change_temperature(-1)

    def _change_temperature(self, delta: int) -> dict:
        with self._command_lock:
            with self._client_factory(self._settings) as client:
                remote_id = self._get_remote_id(client)
                status = client.get_air_conditioner_status(remote_id)
                current_temperature = self._parse_temperature(status)
                target_temperature = current_temperature + delta
                self._validate_temperature(target_temperature)
                cloud_response = client.send_air_conditioner_command(
                    remote_id,
                    "temp",
                    target_temperature,
                )

        action = "temperature_up" if delta > 0 else "temperature_down"
        return self._command_result(
            action,
            cloud_response,
            target_temperature=target_temperature,
        )

    def _send_command(self, action: str, code: str, value: int) -> dict:
        with self._command_lock:
            with self._client_factory(self._settings) as client:
                remote_id = self._get_remote_id(client)
                cloud_response = client.send_air_conditioner_command(
                    remote_id,
                    code,
                    value,
                )
        return self._command_result(action, cloud_response)

    def _get_remote_id(self, client: TuyaClient) -> str:
        if self._remote_id:
            return self._remote_id

        remotes = client.list_remotes()
        air_conditioners = [
            remote
            for remote in remotes
            if self._is_air_conditioner(remote)
        ]
        if len(air_conditioners) != 1:
            raise AirConditionerServiceError(
                "Expected exactly one bound air-conditioner remote, "
                f"found {len(air_conditioners)}"
            )

        remote_id = str(air_conditioners[0].get("remote_id", "")).strip()
        if not remote_id:
            raise AirConditionerServiceError(
                "The bound air-conditioner remote has no remote_id"
            )
        self._remote_id = remote_id
        return remote_id

    @staticmethod
    def _is_air_conditioner(remote: dict) -> bool:
        try:
            category_id = int(remote.get("category_id"))
        except (TypeError, ValueError):
            return False
        return category_id == AIR_CONDITIONER_CATEGORY_ID

    @staticmethod
    def _parse_temperature(status: dict) -> int:
        raw_temperature = status.get("temp")
        try:
            return int(raw_temperature)
        except (TypeError, ValueError) as exc:
            raise AirConditionerServiceError(
                "Tuya did not return a valid current AC temperature"
            ) from exc

    @staticmethod
    def _validate_temperature(temperature: int) -> None:
        if not MINIMUM_TEMPERATURE_C <= temperature <= MAXIMUM_TEMPERATURE_C:
            raise AirConditionerServiceError(
                "Target AC temperature must be between "
                f"{MINIMUM_TEMPERATURE_C} and {MAXIMUM_TEMPERATURE_C} degrees"
            )

    @staticmethod
    def _command_result(
        action: str,
        cloud_response: dict,
        target_temperature: int | None = None,
    ) -> dict:
        result = {
            "ok": True,
            "status": "command_sent",
            "action": action,
            "cloud_success": cloud_response.get("success", True),
            "warning": "Infrared is one-way; physical state is not confirmed.",
        }
        if target_temperature is not None:
            result["target_temperature_c"] = target_temperature
        return result
