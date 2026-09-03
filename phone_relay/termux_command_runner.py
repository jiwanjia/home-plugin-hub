"""Run Shizuku and Termux commands with bounded, explicit failures."""

from __future__ import annotations

import base64
import subprocess
from typing import List


MAX_OUTPUT_BYTES = 64 * 1024


def run_process(command: List[str], timeout: int, binary: bool = False):
    return subprocess.run(
        command,
        capture_output=True,
        text=not binary,
        timeout=timeout,
        check=False,
    )


def run_rish(command: str, timeout: int) -> str:
    try:
        completed = run_process(["rish", "-c", command], timeout)
    except FileNotFoundError as error:
        raise RuntimeError(
            "shizuku_unavailable: rish command is not installed"
        ) from error
    except subprocess.TimeoutExpired as error:
        raise TimeoutError("rish command timed out") from error

    output = ((completed.stdout or "") + (completed.stderr or "")).strip()
    if completed.returncode != 0:
        raise RuntimeError(
            f"rish_failed: exit={completed.returncode}; output={output[:2000]}"
        )
    return output[:MAX_OUTPUT_BYTES]


def run_termux(command: List[str], timeout: int) -> str:
    try:
        completed = run_process(command, timeout)
    except FileNotFoundError as error:
        raise RuntimeError(f"termux_api_unavailable: {command[0]}") from error
    except subprocess.TimeoutExpired as error:
        raise TimeoutError(f"{command[0]} timed out") from error

    output = ((completed.stdout or "") + (completed.stderr or "")).strip()
    if completed.returncode != 0:
        raise RuntimeError(
            f"termux_command_failed: exit={completed.returncode}; output={output[:2000]}"
        )
    return output[:MAX_OUTPUT_BYTES]


def capture_screenshot(timeout: int) -> str:
    try:
        completed = run_process(
            ["rish", "-c", "screencap -p"],
            timeout,
            binary=True,
        )
    except FileNotFoundError as error:
        raise RuntimeError(
            "shizuku_unavailable: rish command is not installed"
        ) from error
    except subprocess.TimeoutExpired as error:
        raise TimeoutError("screenshot timed out") from error
    if completed.returncode != 0:
        stderr = (completed.stderr or b"").decode("utf-8", errors="replace")
        raise RuntimeError(f"screenshot_failed: {stderr[:2000]}")
    return base64.b64encode(completed.stdout or b"").decode("ascii")
