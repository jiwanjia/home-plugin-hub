"""Persistent BLE session lifecycle for verified Cici commands."""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
from contextlib import suppress
from typing import Any, Sequence

from .cici_ble_protocol import CiciBleProfile
from .cici_ble_transport import CiciBleTransport


logger = logging.getLogger(__name__)


class CiciBleSession:
    """Own one reusable Cici BLE connection on a dedicated event loop."""

    def __init__(
        self,
        scanner_type: Any = None,
        client_type: Any = None,
    ) -> None:
        self._transport = CiciBleTransport(scanner_type, client_type)
        self._thread_lock = threading.Lock()
        self._thread_ready = threading.Event()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._operation_lock: asyncio.Lock | None = None
        self._scheduled_task: asyncio.Task | None = None
        self._generation = 0
        self._closed = False

    def apply(
        self,
        profile: CiciBleProfile,
        payload: bytes,
        duration_seconds: float | None,
    ) -> None:
        """Write one payload and leave its lifecycle in the background."""
        self._submit(
            self._apply(profile, payload, duration_seconds),
            self._command_timeout(profile),
        )

    def ramp(
        self,
        profile: CiciBleProfile,
        payloads: Sequence[bytes],
        step_seconds: float,
    ) -> None:
        """Write the first ramp step and schedule the remaining steps."""
        if not payloads:
            raise ValueError("Cici ramp requires at least one payload")
        self._submit(
            self._start_ramp(profile, list(payloads), step_seconds),
            self._command_timeout(profile),
        )

    def stop(self, profile: CiciBleProfile) -> bool:
        """Stop the active session and report whether a connection was running."""
        if not self._worker_is_running():
            return False
        return bool(
            self._submit(
                self._stop(profile),
                self._command_timeout(profile),
            )
        )

    def close(self) -> None:
        """Best-effort stop, disconnect, and terminate the worker thread."""
        with self._thread_lock:
            thread = self._thread
            loop = self._loop
            self._closed = True

        if thread is None or loop is None or not thread.is_alive():
            return

        shutdown = asyncio.run_coroutine_threadsafe(self._shutdown(), loop)
        try:
            shutdown.result(timeout=5)
        except Exception:
            logger.exception("Cici BLE session shutdown did not finish cleanly")
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=5)

    async def _apply(
        self,
        profile: CiciBleProfile,
        payload: bytes,
        duration_seconds: float | None,
    ) -> None:
        async with self._required_operation_lock():
            await self._cancel_schedule()
            try:
                await self._ensure_connected(profile)
                await self._write_command(profile, payload)
            except Exception:
                await self._transport.disconnect()
                raise

            self._generation += 1
            if duration_seconds is not None:
                self._scheduled_task = asyncio.create_task(
                    self._auto_stop_after(
                        profile,
                        self._generation,
                        duration_seconds,
                    )
                )

    async def _start_ramp(
        self,
        profile: CiciBleProfile,
        payloads: list[bytes],
        step_seconds: float,
    ) -> None:
        async with self._required_operation_lock():
            await self._cancel_schedule()
            try:
                await self._ensure_connected(profile)
                await self._write_command(profile, payloads[0])
            except Exception:
                await self._transport.disconnect()
                raise

            self._generation += 1
            self._scheduled_task = asyncio.create_task(
                self._continue_ramp(
                    profile,
                    self._generation,
                    payloads[1:],
                    step_seconds,
                )
            )

    async def _stop(self, profile: CiciBleProfile) -> bool:
        async with self._required_operation_lock():
            await self._cancel_schedule()
            if not self._transport.is_connected:
                await self._transport.disconnect()
                return False

            try:
                await self._write_stop(profile)
            finally:
                await self._transport.disconnect()
            return True

    async def _auto_stop_after(
        self,
        profile: CiciBleProfile,
        generation: int,
        duration_seconds: float,
    ) -> None:
        try:
            await asyncio.sleep(duration_seconds)
            async with self._required_operation_lock():
                if generation != self._generation:
                    return
                await self._write_stop(profile)
                await self._transport.disconnect()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Cici timed stop failed")
            await self._transport.disconnect()
        finally:
            self._clear_current_schedule()

    async def _continue_ramp(
        self,
        profile: CiciBleProfile,
        generation: int,
        remaining_payloads: list[bytes],
        step_seconds: float,
    ) -> None:
        try:
            for payload in remaining_payloads:
                await asyncio.sleep(step_seconds)
                async with self._required_operation_lock():
                    if generation != self._generation:
                        return
                    await self._write_command(profile, payload)

            await asyncio.sleep(step_seconds)
            async with self._required_operation_lock():
                if generation != self._generation:
                    return
                await self._write_stop(profile)
                await self._transport.disconnect()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Cici ramp failed")
            await self._transport.disconnect()
        finally:
            self._clear_current_schedule()

    async def _shutdown(self) -> None:
        async with self._required_operation_lock():
            await self._cancel_schedule()
            profile = self._transport.profile
            if self._transport.is_connected and profile is not None:
                with suppress(Exception):
                    await self._write_stop(profile)
            await self._transport.disconnect()

    async def _ensure_connected(self, profile: CiciBleProfile) -> None:
        await self._transport.ensure_connected(
            profile,
            self._on_disconnected,
        )

    async def _write_command(
        self,
        profile: CiciBleProfile,
        payload: bytes,
    ) -> None:
        await self._transport.write_command(profile, payload)

    async def _write_stop(self, profile: CiciBleProfile) -> None:
        if not self._transport.is_connected:
            return
        stop_payload = profile.resolve_command("stop", None)
        await self._write_command(profile, stop_payload)

    async def _cancel_schedule(self) -> None:
        self._generation += 1
        scheduled = self._scheduled_task
        self._scheduled_task = None
        if scheduled is None or scheduled is asyncio.current_task():
            return
        scheduled.cancel()
        with suppress(asyncio.CancelledError):
            await scheduled

    def _clear_current_schedule(self) -> None:
        if self._scheduled_task is asyncio.current_task():
            self._scheduled_task = None

    def _on_disconnected(self) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(self._generation_changed)

    def _generation_changed(self) -> None:
        self._generation += 1

    def _submit(self, coroutine: Any, timeout: float) -> Any:
        try:
            loop = self._ensure_worker()
        except Exception:
            coroutine.close()
            raise
        future = asyncio.run_coroutine_threadsafe(coroutine, loop)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            raise RuntimeError("Cici BLE worker did not finish the command") from exc

    def _ensure_worker(self) -> asyncio.AbstractEventLoop:
        with self._thread_lock:
            if self._closed:
                raise RuntimeError("Cici BLE session has been closed")
            if self._thread is None or not self._thread.is_alive():
                self._thread_ready.clear()
                self._thread = threading.Thread(
                    target=self._run_worker,
                    name="cici-ble-session",
                    daemon=True,
                )
                self._thread.start()

        if not self._thread_ready.wait(timeout=5):
            raise RuntimeError("Cici BLE worker did not start")
        if self._loop is None:
            raise RuntimeError("Cici BLE worker has no event loop")
        return self._loop

    def _run_worker(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._operation_lock = asyncio.Lock()
        self._thread_ready.set()
        try:
            loop.run_forever()
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
            loop.close()

    def _required_operation_lock(self) -> asyncio.Lock:
        if self._operation_lock is None:
            raise RuntimeError("Cici BLE worker is not ready")
        return self._operation_lock

    def _worker_is_running(self) -> bool:
        with self._thread_lock:
            return self._thread is not None and self._thread.is_alive()

    @staticmethod
    def _command_timeout(profile: CiciBleProfile) -> float:
        return (
            profile.scan_timeout_seconds
            + profile.connect_timeout_seconds
            + 2.0
        )
