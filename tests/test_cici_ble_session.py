"""Offline lifecycle tests for the persistent Cici BLE session."""

from __future__ import annotations

import time

import pytest

from mcp_plugins.cici_ble_protocol import CiciBleProfile
from mcp_plugins.cici_ble_session import CiciBleSession


START = bytes.fromhex("55 03 00 00 01 01 00")
STRONGER = bytes.fromhex("55 03 00 00 01 02 00")
STRONGEST = bytes.fromhex("55 03 00 00 01 03 00")
STOP = bytes.fromhex("55 03 00 00 00 00 00")


class FakeDevice:
    name = "Cici+ 2"


class FakeScanner:
    @staticmethod
    async def find_device_by_filter(filter_function, timeout):
        del timeout
        advertisement = type(
            "Advertisement",
            (),
            {
                "local_name": "Cici+ 2",
                "service_uuids": ["service"],
            },
        )()
        device = FakeDevice()
        assert filter_function(device, advertisement) is True
        return device


class FakeClient:
    instances = []

    def __init__(self, device, timeout, disconnected_callback):
        del device
        del timeout
        self.disconnected_callback = disconnected_callback
        self.notification_callback = None
        self.is_connected = False
        self.writes = []
        self.__class__.instances.append(self)

    async def connect(self):
        self.is_connected = True

    async def start_notify(self, characteristic, callback):
        del characteristic
        self.notification_callback = callback

    async def write_gatt_char(self, characteristic, payload, response):
        del characteristic
        del response
        self.writes.append(bytes(payload))

    async def disconnect(self):
        if not self.is_connected:
            return
        self.is_connected = False
        self.disconnected_callback(self)

    def drop_connection(self):
        self.is_connected = False
        self.disconnected_callback(self)


@pytest.fixture(autouse=True)
def reset_fake_client():
    FakeClient.instances = []
    yield


@pytest.fixture
def profile():
    return CiciBleProfile(
        device_name="Cici+ 2",
        service_uuid="service",
        write_characteristic="write",
        notify_characteristic="notify",
        write_with_response=True,
        commands={"start": START, "stop": STOP},
        intensities={1: START, 2: STRONGER, 3: STRONGEST},
        patterns={1: START},
        scan_timeout_seconds=0.05,
        connect_timeout_seconds=0.05,
        notification_timeout_seconds=0.03,
    )


def make_session():
    return CiciBleSession(
        scanner_type=FakeScanner,
        client_type=FakeClient,
    )


def wait_until(predicate, timeout=0.5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


def test_written_update_reuses_active_connection_without_notification(profile):
    session = make_session()
    try:
        session.apply(profile, START, duration_seconds=None)
        session.apply(profile, STRONGER, duration_seconds=None)

        assert len(FakeClient.instances) == 1
        client = FakeClient.instances[0]
        assert client.is_connected is True
        assert client.writes == [START, STRONGER]
        assert session.stop(profile) is True
        assert client.writes == [START, STRONGER, STOP]
        assert client.is_connected is False
    finally:
        session.close()


def test_timed_action_returns_before_background_stop(profile):
    session = make_session()
    try:
        session.apply(profile, START, duration_seconds=0.04)
        client = FakeClient.instances[0]

        assert client.is_connected is True
        assert client.writes == [START]
        assert wait_until(lambda: client.writes == [START, STOP])
        assert client.is_connected is False
    finally:
        session.close()


def test_new_indefinite_action_cancels_previous_auto_stop(profile):
    session = make_session()
    try:
        session.apply(profile, START, duration_seconds=0.05)
        client = FakeClient.instances[0]
        time.sleep(0.015)

        session.apply(profile, STRONGER, duration_seconds=None)
        time.sleep(0.08)

        assert client.writes == [START, STRONGER]
        assert client.is_connected is True
        session.stop(profile)
    finally:
        session.close()


def test_stop_interrupts_background_ramp(profile):
    session = make_session()
    try:
        session.ramp(
            profile,
            [START, STRONGER, STRONGEST],
            step_seconds=0.04,
        )
        client = FakeClient.instances[0]
        assert client.writes == [START]
        assert wait_until(lambda: len(client.writes) >= 2)

        assert session.stop(profile) is True
        writes_after_stop = list(client.writes)
        time.sleep(0.1)

        assert writes_after_stop[-1] == STOP
        assert client.writes == writes_after_stop
    finally:
        session.close()


def test_device_notification_is_not_required_to_keep_connection(profile):
    session = make_session()
    try:
        session.apply(profile, START, duration_seconds=None)

        client = FakeClient.instances[0]
        assert client.writes == [START]
        assert client.is_connected is True
        session.stop(profile)
    finally:
        session.close()


def test_unexpected_disconnect_reconnects_on_next_command(profile):
    session = make_session()
    try:
        session.apply(profile, START, duration_seconds=None)
        first_client = FakeClient.instances[0]
        first_client.drop_connection()

        session.apply(profile, STRONGER, duration_seconds=None)

        assert len(FakeClient.instances) == 2
        assert FakeClient.instances[1].writes == [STRONGER]
    finally:
        session.close()


def test_idle_stop_does_not_scan_and_close_stops_active_session(profile):
    idle_session = make_session()
    assert idle_session.stop(profile) is False
    assert FakeClient.instances == []
    idle_session.close()

    active_session = make_session()
    active_session.apply(profile, START, duration_seconds=None)
    client = FakeClient.instances[0]
    active_session.close()

    assert client.writes == [START, STOP]
    assert client.is_connected is False
