"""Bleak transport for one reusable Cici BLE connection."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import Any, Callable

from .cici_ble_protocol import CiciBleProfile


logger = logging.getLogger(__name__)


class CiciBleTransport:
    """Discover Cici, own its Bleak client, and write verified commands."""

    def __init__(self, scanner_type: Any = None, client_type: Any = None) -> None:
        self._scanner_type = scanner_type
        self._client_type = client_type
        self._client: Any = None
        self._profile: CiciBleProfile | None = None
        self._disconnect_callback: Callable[[], None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def profile(self) -> CiciBleProfile | None:
        return self._profile

    @property
    def is_connected(self) -> bool:
        return self._client is not None and bool(self._client.is_connected)

    async def ensure_connected(
        self,
        profile: CiciBleProfile,
        disconnect_callback: Callable[[], None],
    ) -> None:
        if self.is_connected and self._matches_profile(profile):
            return
        if self.is_connected:
            await self.disconnect()

        scanner_type, client_type = self._bleak_types()
        device = await self._find_device(profile, scanner_type)
        client = client_type(
            device,
            timeout=profile.connect_timeout_seconds,
            disconnected_callback=self._on_disconnected,
        )
        try:
            await client.connect()
            await client.start_notify(
                profile.notify_characteristic,
                self._on_notification,
            )
        except Exception:
            if client.is_connected:
                with suppress(Exception):
                    await client.disconnect()
            raise

        self._client = client
        self._profile = profile
        self._disconnect_callback = disconnect_callback
        self._loop = asyncio.get_running_loop()

    async def write_command(
        self,
        profile: CiciBleProfile,
        payload: bytes,
    ) -> None:
        if not self.is_connected:
            raise RuntimeError("Cici BLE session is not connected")

        await self._client.write_gatt_char(
            profile.write_characteristic,
            payload,
            response=profile.write_with_response,
        )

    async def disconnect(self) -> None:
        client = self._client
        self._client = None
        self._profile = None
        self._disconnect_callback = None
        self._loop = None
        if client is not None and client.is_connected:
            with suppress(Exception):
                await client.disconnect()

    def _on_notification(self, sender: Any, data: bytearray) -> None:
        del sender
        logger.debug("Cici BLE notification received: %d bytes", len(data))

    def _on_disconnected(self, client: Any) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(self._handle_disconnected, client)

    def _handle_disconnected(self, client: Any) -> None:
        if client is not self._client:
            return
        self._client = None
        self._profile = None
        self._loop = None
        callback = self._disconnect_callback
        self._disconnect_callback = None
        if callback is not None:
            callback()

    def _matches_profile(self, profile: CiciBleProfile) -> bool:
        active = self._profile
        if active is None:
            return False
        return self._profile_key(active) == self._profile_key(profile)

    def _bleak_types(self) -> tuple[Any, Any]:
        if self._scanner_type is not None and self._client_type is not None:
            return self._scanner_type, self._client_type
        from bleak import BleakClient, BleakScanner

        return BleakScanner, BleakClient

    @staticmethod
    async def _find_device(profile: CiciBleProfile, scanner_type: Any) -> Any:
        expected_name = profile.device_name.casefold()

        def matches(device: Any, advertisement_data: Any) -> bool:
            names = [device.name, advertisement_data.local_name]
            name_match = any(
                isinstance(name, str) and name.casefold() == expected_name
                for name in names
            )
            advertised = {
                value.casefold()
                for value in (advertisement_data.service_uuids or [])
            }
            service_match = bool(
                profile.service_uuid
                and profile.service_uuid.casefold() in advertised
            )
            return name_match or service_match

        device = await scanner_type.find_device_by_filter(
            matches,
            timeout=profile.scan_timeout_seconds,
        )
        if device is None:
            raise RuntimeError("Cici was not found nearby or is already connected")
        return device

    @staticmethod
    def _profile_key(profile: CiciBleProfile) -> tuple[Any, ...]:
        return (
            profile.device_name,
            profile.service_uuid,
            profile.write_characteristic,
            profile.notify_characteristic,
        )
