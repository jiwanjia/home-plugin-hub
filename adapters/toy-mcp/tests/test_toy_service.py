"""Offline behavior tests for patting-toy actions."""

from __future__ import annotations

from app.config import Settings
from app.exceptions import ToyCooldownError, ToyRoutineStepError
from app.toy_service import ToyService


class FakeClient:
    def __init__(self, settings, sent, fail_code=None):
        self._sent = sent
        self._fail_code = fail_code

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def send_learning_code(self, code):
        if code == self._fail_code:
            raise RuntimeError("cloud rejected command")
        self._sent.append(code)
        return {"success": True, "result": True}


def _settings(**overrides):
    values = {
        "tuya_access_id": "id",
        "tuya_access_secret": "secret",
        "tuya_infrared_id": "ir",
        "tuya_remote_id": "remote",
        "toy_power_code": "power",
        "toy_pat_code": "pat",
        "toy_slow_code": "slow",
        "toy_fast_code": "fast",
        "toy_command_cooldown_seconds": 2,
    }
    values.update(overrides)
    return Settings(**values)


def _service(settings=None, fail_code=None):
    sent = []
    now = [0.0]

    def clock():
        return now[0]

    def sleep(seconds):
        now[0] += seconds

    def factory(current_settings):
        return FakeClient(current_settings, sent, fail_code=fail_code)

    service = ToyService(
        settings or _settings(),
        client_factory=factory,
        clock=clock,
        sleeper=sleep,
    )
    return service, sent, now


def test_single_command_returns_one_way_result():
    service, sent, _ = _service()
    result = service.power_toggle()
    assert sent == ["power"]
    assert result["status"] == "command_sent"
    assert "not confirmed" in result["warning"]


def test_direct_commands_respect_cooldown():
    service, _, _ = _service()
    service.power_toggle()
    try:
        service.pat_toggle()
    except ToyCooldownError:
        pass
    else:
        raise AssertionError("cooldown was not enforced")


def test_soothe_sleep_waits_and_finishes():
    service, sent, now = _service()
    result = service.soothe_sleep(delay_after_power=5)
    assert sent == ["power", "pat", "slow"]
    assert result["completed_steps"] == [
        "power_toggle",
        "pat_toggle",
        "speed_slower",
    ]
    assert now[0] >= 7


def test_soothe_sleep_reports_completed_steps():
    service, sent, _ = _service(fail_code="pat")
    try:
        service.soothe_sleep(delay_after_power=1)
    except ToyRoutineStepError as exc:
        assert exc.completed_steps == ["power_toggle"]
        assert sent == ["power"]
    else:
        raise AssertionError("routine failure was not reported")
