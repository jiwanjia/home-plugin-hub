"""Thread-safe, single-device request registry used by API and Hub plugin."""

from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, Optional

from .contracts import PhoneCommand, PhoneResult, utc_now


MAX_AGENT_VERSION_LENGTH = 32


class PhoneRelayTimeout(TimeoutError):
    """Raised when the phone does not complete a request before its deadline."""


@dataclass
class _PendingRequest:
    completed: threading.Event = field(default_factory=threading.Event)
    result: Optional[PhoneResult] = None


class PhoneRelayRegistry:
    """Coordinate one outbound phone agent with synchronous Hub calls."""

    def __init__(self, online_window_seconds: int = 45):
        self._online_window_seconds = online_window_seconds
        self._condition = threading.Condition()
        self._commands: Deque[PhoneCommand] = deque()
        self._pending: Dict[str, _PendingRequest] = {}
        self._last_poll_monotonic: Optional[float] = None
        self._agent_version: Optional[str] = None

    def note_agent_poll(self, agent_version: Any) -> None:
        """Remember a bounded, display-safe version reported by the phone."""
        if not isinstance(agent_version, str):
            return
        normalized_version = agent_version.strip()
        if not normalized_version or len(normalized_version) > MAX_AGENT_VERSION_LENGTH:
            return
        if not all(
            character.isalnum() or character in ".-_"
            for character in normalized_version
        ):
            return
        with self._condition:
            self._agent_version = normalized_version

    def submit_and_wait(
        self,
        action: str,
        arguments: Dict[str, Any],
        deadline_seconds: int,
    ) -> PhoneResult:
        if not action:
            raise ValueError("action must not be empty")
        if deadline_seconds < 1 or deadline_seconds > 120:
            raise ValueError("deadline_seconds must be between 1 and 120")

        command = PhoneCommand(
            request_id=uuid.uuid4().hex,
            action=action,
            arguments=dict(arguments),
            deadline_seconds=deadline_seconds,
            created_at=utc_now(),
        )
        pending = _PendingRequest()

        with self._condition:
            self._pending[command.request_id] = pending
            self._commands.append(command)
            self._condition.notify_all()

        if not pending.completed.wait(deadline_seconds):
            with self._condition:
                self._pending.pop(command.request_id, None)
                self._remove_queued_command(command.request_id)
            raise PhoneRelayTimeout(
                f"phone did not complete {action} within {deadline_seconds} seconds"
            )

        if pending.result is None:
            raise RuntimeError("phone relay completed without a result")
        return pending.result

    def poll(self, wait_seconds: int) -> Optional[PhoneCommand]:
        bounded_wait = max(1, min(wait_seconds, 30))
        end_at = time.monotonic() + bounded_wait

        with self._condition:
            self._last_poll_monotonic = time.monotonic()
            while not self._commands:
                remaining = end_at - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)
                self._last_poll_monotonic = time.monotonic()
            return self._commands.popleft()

    def complete(self, result: PhoneResult) -> bool:
        with self._condition:
            pending = self._pending.pop(result.request_id, None)
            if pending is None:
                return False
            pending.result = result
            pending.completed.set()
            return True

    def status(self) -> Dict[str, Any]:
        with self._condition:
            last_poll = self._last_poll_monotonic
            pending_count = len(self._pending)
            queued_count = len(self._commands)
            agent_version = self._agent_version

        online = False
        if last_poll is not None:
            online = time.monotonic() - last_poll <= self._online_window_seconds
        return {
            "online": online,
            "agent_version": agent_version,
            "pending_count": pending_count,
            "queued_count": queued_count,
        }

    def _remove_queued_command(self, request_id: str) -> None:
        self._commands = deque(
            command
            for command in self._commands
            if command.request_id != request_id
        )


_PHONE_RELAY_REGISTRY = PhoneRelayRegistry()


def get_phone_relay_registry() -> PhoneRelayRegistry:
    return _PHONE_RELAY_REGISTRY
