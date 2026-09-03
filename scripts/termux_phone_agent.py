#!/usr/bin/env python3
"""Outbound Termux agent for the Continuum phone relay.

Required environment variables:
  PHONE_RELAY_URL   Existing HTTPS origin, without a trailing slash.
  PHONE_RELAY_TOKEN Dedicated phone relay bearer token.
"""

from __future__ import annotations

import json
import http.client
import os
import ssl
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Dict

from phone_relay.termux_executor import execute_command


AGENT_VERSION = "0.2.4"
MAX_OUTPUT_BYTES = 64 * 1024
POLL_WAIT_SECONDS = 10
RETRY_DELAYS_SECONDS = (1, 2, 4, 8, 15)

PostJson = Callable[[str, str, Dict[str, Any]], Dict[str, Any]]
Sleep = Callable[[float], None]
CommandExecutor = Callable[[Dict[str, Any]], Dict[str, Any]]


def required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"missing required environment variable: {name}")
    return value


def post_json(url: str, token: str, body: Dict[str, Any]) -> Dict[str, Any]:
    encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=encoded,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": f"continuum-termux-phone/{AGENT_VERSION}",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=40) as response:
        payload = response.read(MAX_OUTPUT_BYTES)
    return json.loads(payload.decode("utf-8"))


def is_recoverable_relay_error(error: Exception) -> bool:
    if isinstance(error, urllib.error.HTTPError):
        return error.code == 408 or error.code == 429 or error.code >= 500
    return isinstance(
        error,
        (
            OSError,
            TimeoutError,
            json.JSONDecodeError,
            http.client.HTTPException,
            ssl.SSLError,
            urllib.error.URLError,
        ),
    )


def retry_delay_seconds(failure_count: int) -> int:
    index = min(failure_count, len(RETRY_DELAYS_SECONDS) - 1)
    return RETRY_DELAYS_SECONDS[index]


def post_until_success(
    url: str,
    token: str,
    body: Dict[str, Any],
    operation: str,
    post: PostJson,
    sleep: Sleep,
) -> Dict[str, Any]:
    failure_count = 0
    while True:
        try:
            return post(url, token, body)
        except Exception as error:
            if not is_recoverable_relay_error(error):
                raise
            delay = retry_delay_seconds(failure_count)
            error_name = type(error).__name__
            print(
                f"relay {operation} temporarily unavailable: {error_name}; "
                f"retrying in {delay}s",
                flush=True,
            )
            sleep(delay)
            failure_count += 1


def run_forever(
    post: PostJson = post_json,
    sleep: Sleep = time.sleep,
    execute: CommandExecutor = execute_command,
) -> None:
    relay_url = required_environment("PHONE_RELAY_URL").rstrip("/")
    token = required_environment("PHONE_RELAY_TOKEN")
    poll_url = f"{relay_url}/api/phone-relay/poll"
    result_url = f"{relay_url}/api/phone-relay/results"

    while True:
        try:
            response = post_until_success(
                poll_url,
                token,
                {"wait_seconds": POLL_WAIT_SECONDS, "agent_version": AGENT_VERSION},
                "poll",
                post,
                sleep,
            )
            command = response.get("command")
            if not isinstance(command, dict):
                continue
            result = execute(command)
            post_until_success(
                result_url,
                token,
                result,
                "result delivery",
                post,
                sleep,
            )
        except KeyboardInterrupt:
            return


if __name__ == "__main__":
    run_forever()
