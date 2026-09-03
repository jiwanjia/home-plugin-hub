"""Serializable command and result contracts for the phone relay."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict


RESULT_STATUSES = {"completed", "failed", "timed_out", "unsupported"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class PhoneCommand:
    request_id: str
    action: str
    arguments: Dict[str, Any]
    deadline_seconds: int
    created_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "action": self.action,
            "arguments": self.arguments,
            "deadline_seconds": self.deadline_seconds,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class PhoneResult:
    request_id: str
    ok: bool
    status: str
    output: str
    error: str
    observed_at: str

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "PhoneResult":
        request_id = value.get("request_id")
        ok = value.get("ok")
        status = value.get("status")
        output = value.get("output", "")
        error = value.get("error", "")
        observed_at = value.get("observed_at")

        if not isinstance(request_id, str) or not request_id:
            raise ValueError("request_id must be a non-empty string")
        if not isinstance(ok, bool):
            raise ValueError("ok must be a boolean")
        if status not in RESULT_STATUSES:
            raise ValueError("status is invalid")
        if not isinstance(output, str):
            raise ValueError("output must be a string")
        if not isinstance(error, str):
            raise ValueError("error must be a string")
        if not isinstance(observed_at, str) or not observed_at:
            raise ValueError("observed_at must be a non-empty string")
        if ok and status != "completed":
            raise ValueError("only completed results may set ok=true")
        if not ok and status == "completed":
            raise ValueError("completed results must set ok=true")

        return cls(
            request_id=request_id,
            ok=ok,
            status=status,
            output=output,
            error=error,
            observed_at=observed_at,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "ok": self.ok,
            "status": self.status,
            "output": self.output,
            "error": self.error,
            "observed_at": self.observed_at,
        }
