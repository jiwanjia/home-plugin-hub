"""Offline behavior tests for Tuya infrared air-conditioner actions."""

from __future__ import annotations

import pytest

from app.air_conditioner_service import AirConditionerService
from app.config import Settings
from app.exceptions import AirConditionerServiceError


class FakeClient:
    def __init__(self, settings, state, remotes, sent):
        self._state = state
        self._remotes = remotes
        self._sent = sent

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def list_remotes(self):
        return list(self._remotes)

    def get_air_conditioner_status(self, remote_id):
        return dict(self._state)

    def send_air_conditioner_command(self, remote_id, code, value):
        self._sent.append((remote_id, code, value))
        return {"success": True, "result": True}


def _settings():
    return Settings(
        tuya_access_id="id",
        tuya_access_secret="secret",
        tuya_infrared_id="ir",
    )


def _service(temperature="24", remotes=None):
    sent = []
    configured_remotes = remotes or [
        {"remote_id": "toy", "category_id": 13},
        {"remote_id": "ac", "category_id": 5},
    ]

    def factory(settings):
        return FakeClient(
            settings,
            {"power": "1", "temp": temperature},
            configured_remotes,
            sent,
        )

    return AirConditionerService(_settings(), client_factory=factory), sent


def test_power_actions_are_explicit_not_toggle():
    service, sent = _service()

    on_result = service.power_on()
    off_result = service.power_off()

    assert sent == [("ac", "power", 1), ("ac", "power", 0)]
    assert on_result["action"] == "power_on"
    assert off_result["action"] == "power_off"


@pytest.mark.parametrize(
    ("action", "temperature", "expected"),
    [
        ("temperature_up", "24", 25),
        ("temperature_down", "24", 23),
    ],
)
def test_temperature_actions_read_then_change_one_degree(
    action,
    temperature,
    expected,
):
    service, sent = _service(temperature=temperature)

    result = getattr(service, action)()

    assert sent == [("ac", "temp", expected)]
    assert result["target_temperature_c"] == expected


@pytest.mark.parametrize(
    ("action", "temperature"),
    [
        ("temperature_up", "30"),
        ("temperature_down", "16"),
    ],
)
def test_temperature_actions_reject_out_of_range(action, temperature):
    service, sent = _service(temperature=temperature)

    with pytest.raises(AirConditionerServiceError, match="between 16 and 30"):
        getattr(service, action)()

    assert sent == []


def test_exactly_one_air_conditioner_remote_is_required():
    service, _ = _service(remotes=[{"remote_id": "toy", "category_id": 13}])

    with pytest.raises(AirConditionerServiceError, match="found 0"):
        service.power_on()


def test_string_category_id_is_accepted():
    service, sent = _service(
        remotes=[{"remote_id": "ac", "category_id": "5"}]
    )

    service.power_on()

    assert sent == [("ac", "power", 1)]
