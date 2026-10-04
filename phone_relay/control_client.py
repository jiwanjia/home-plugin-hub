"""Loopback client for the authoritative backend phone relay."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict

from .contracts import PhoneResult
from .registry import PhoneRelayTimeout


DEFAULT_RELAY_API_URL = "http://127.0.0.1:8000/api/phone-relay"
DEFAULT_RELAY_TOKEN_PATH = Path("/data/phone-relay-token")


class PhoneRelayControlClient:
    """Submit Hub requests to the backend process that owns the relay queue."""

    def __init__(
        self,
        api_url: str | None = None,
        token_path: Path | None = None,
    ) -> None:
        self._api_url = (
            api_url
            or os.environ.get("PHONE_RELAY_CONTROL_URL")
            or DEFAULT_RELAY_API_URL
        ).rstrip("/")
        configured_token_path = os.environ.get("PHONE_RELAY_TOKEN_PATH")
        self._token_path = token_path or Path(
            configured_token_path or DEFAULT_RELAY_TOKEN_PATH
        )

    def status(self) -> Dict[str, Any]:
        return self._request("GET", "/health", None, timeout_seconds=5)

    def submit_and_wait(
        self,
        action: str,
        arguments: Dict[str, Any],
        deadline_seconds: int,
    ) -> PhoneResult:
        payload = {
            "action": action,
            "arguments": arguments,
            "deadline_seconds": deadline_seconds,
        }
        response = self._request(
            "POST",
            "/commands",
            payload,
            timeout_seconds=deadline_seconds + 5,
        )
        return PhoneResult.from_dict(response)

    def _request(
        self,
        method: str,
        path: str,
        body: Dict[str, Any] | None,
        timeout_seconds: int,
    ) -> Dict[str, Any]:
        token = self._read_token()
        encoded_body = None
        if body is not None:
            encoded_body = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            self._api_url + path,
            data=encoded_body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=timeout_seconds,
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            raise ValueError(
                f"phone relay backend rejected the request: HTTP {error.code}"
            ) from error
        except (OSError, urllib.error.URLError, TimeoutError) as error:
            raise PhoneRelayTimeout(
                "phone relay backend is unavailable"
            ) from error
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("phone relay backend returned invalid JSON") from error
        if not isinstance(payload, dict):
            raise ValueError("phone relay backend returned an invalid response")
        return payload

    def _read_token(self) -> str:
        try:
            token = self._token_path.read_text(encoding="utf-8").strip()
        except OSError as error:
            raise ValueError("phone relay token is unavailable") from error
        if len(token) < 32:
            raise ValueError("phone relay token is invalid")
        return token


_PHONE_RELAY_CONTROL_CLIENT = PhoneRelayControlClient()


def get_phone_relay_control_client() -> PhoneRelayControlClient:
    return _PHONE_RELAY_CONTROL_CLIENT
