"""Load the dedicated phone relay token without exposing its value."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Protocol


class PhoneRelaySettings(Protocol):
    phone_relay_token: Optional[str]
    phone_relay_token_path: Path


class InvalidPhoneRelayTokenFile(ValueError):
    """Raised when a configured token file contains an invalid value."""


def configured_phone_relay_token(
    settings: PhoneRelaySettings,
) -> Optional[str]:
    if settings.phone_relay_token:
        return settings.phone_relay_token

    token_path = settings.phone_relay_token_path
    if not token_path.is_file():
        return None
    token = token_path.read_text(encoding="utf-8").strip()
    if len(token) < 32:
        raise InvalidPhoneRelayTokenFile(
            "phone relay token file must contain at least 32 characters"
        )
    return token
