"""Execute relay actions inside Termux and report post-action UI state."""

from __future__ import annotations

import json
import shlex
import time
from datetime import datetime, timezone
from typing import Any, Dict

from .termux_command_runner import capture_screenshot, run_rish, run_termux
from .ui_reader import read_ui_snapshot


DEFAULT_COMMAND_TIMEOUT = 30
COMMAND_RESULT_MARGIN_SECONDS = 1
POST_ACTION_FOREGROUND_TIMEOUT_SECONDS = 3
POST_ACTION_UI_TIMEOUT_SECONDS = 12
POST_ACTION_OBSERVATION_RESERVE_SECONDS = (
    POST_ACTION_FOREGROUND_TIMEOUT_SECONDS
    + POST_ACTION_UI_TIMEOUT_SECONDS
    + COMMAND_RESULT_MARGIN_SECONDS
)
INTERACTIVE_ACTIONS = {
    "tap",
    "swipe",
    "text",
    "key",
    "app_launch",
    "force_stop",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def integer_argument(arguments: Dict[str, Any], name: str) -> int:
    value = arguments.get(name)
    if not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def text_argument(arguments: Dict[str, Any], name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def execute_action(action: str, arguments: Dict[str, Any], timeout: int) -> str:
    if action == "screen_status":
        return run_rish("dumpsys power | grep mWakefulness", timeout)
    if action == "foreground_app":
        return run_rish(
            "dumpsys activity activities | grep topResumedActivity",
            timeout,
        )
    if action == "battery":
        return run_rish("dumpsys battery", timeout)
    if action == "media_status":
        return run_rish("dumpsys media_session", timeout)
    if action in {"ui_read", "ui_dump"}:
        return json.dumps(read_ui_snapshot(timeout), ensure_ascii=False)
    if action == "tap":
        x = integer_argument(arguments, "x")
        y = integer_argument(arguments, "y")
        return run_rish(f"input tap {x} {y}", timeout)
    if action == "swipe":
        x1 = integer_argument(arguments, "x1")
        y1 = integer_argument(arguments, "y1")
        x2 = integer_argument(arguments, "x2")
        y2 = integer_argument(arguments, "y2")
        duration_ms = int(arguments.get("duration_ms", 300))
        return run_rish(
            f"input swipe {x1} {y1} {x2} {y2} {duration_ms}",
            timeout,
        )
    if action == "text":
        value = shlex.quote(text_argument(arguments, "text"))
        return run_rish(f"input text {value}", timeout)
    if action == "key":
        keycode = integer_argument(arguments, "keycode")
        return run_rish(f"input keyevent {keycode}", timeout)
    if action == "app_launch":
        package = shlex.quote(text_argument(arguments, "package"))
        return run_rish(
            f"monkey -p {package} -c android.intent.category.LAUNCHER 1",
            timeout,
        )
    if action == "force_stop":
        package = shlex.quote(text_argument(arguments, "package"))
        return run_rish(f"am force-stop {package}", timeout)
    if action == "notify":
        title = text_argument(arguments, "title")
        content = text_argument(arguments, "content")
        return run_termux(
            ["termux-notification", "--title", title, "--content", content],
            timeout,
        )
    if action == "vibrate":
        duration_ms = int(arguments.get("duration_ms", 500))
        return run_termux(
            ["termux-vibrate", "-d", str(duration_ms)],
            timeout,
        )
    if action == "screenshot":
        return capture_screenshot(timeout)
    if action == "rish_command":
        command = text_argument(arguments, "command")
        return run_rish(command, timeout)
    raise NotImplementedError(f"unsupported action: {action}")


def observe_ui_state(
    foreground_timeout: int,
    ui_timeout: int,
) -> Dict[str, Any]:
    foreground_app = run_rish(
        "dumpsys activity activities | grep topResumedActivity",
        foreground_timeout,
    )
    ui_dump = read_ui_snapshot(ui_timeout)
    return {
        "state_known": True,
        "foreground_app": foreground_app,
        "ui_dump": ui_dump,
    }


def action_output_with_observation(
    action_output: str,
    foreground_timeout: int,
    ui_timeout: int,
) -> str:
    result: Dict[str, Any] = {"action_output": action_output}
    try:
        result.update(observe_ui_state(foreground_timeout, ui_timeout))
    except Exception as error:
        result.update(
            {
                "state_known": False,
                "observation_error": str(error),
            }
        )
    return json.dumps(result, ensure_ascii=False)


def execute_command(command: Dict[str, Any]) -> Dict[str, Any]:
    request_id = str(command.get("request_id", ""))
    action = str(command.get("action", ""))
    arguments = command.get("arguments")
    if not isinstance(arguments, dict):
        arguments = {}
    deadline_seconds = command.get("deadline_seconds", DEFAULT_COMMAND_TIMEOUT)
    timeout = max(1, min(int(deadline_seconds), 120))
    started_at = time.monotonic()
    reserved_seconds = COMMAND_RESULT_MARGIN_SECONDS
    if action in INTERACTIVE_ACTIONS:
        reserved_seconds = POST_ACTION_OBSERVATION_RESERVE_SECONDS
    action_timeout = max(1, timeout - reserved_seconds)

    try:
        output = execute_action(action, arguments, action_timeout)
        if action in INTERACTIVE_ACTIONS:
            elapsed = time.monotonic() - started_at
            remaining = int(timeout - elapsed)
            if remaining < POST_ACTION_OBSERVATION_RESERVE_SECONDS:
                output = json.dumps(
                    {
                        "action_output": output,
                        "state_known": False,
                        "observation_error": "deadline budget exhausted",
                    },
                    ensure_ascii=False,
                )
            else:
                output = action_output_with_observation(
                    output,
                    POST_ACTION_FOREGROUND_TIMEOUT_SECONDS,
                    POST_ACTION_UI_TIMEOUT_SECONDS,
                )
        return {
            "request_id": request_id,
            "ok": True,
            "status": "completed",
            "output": output,
            "error": "",
            "observed_at": utc_now(),
        }
    except NotImplementedError as error:
        status = "unsupported"
        message = str(error)
    except TimeoutError as error:
        status = "timed_out"
        message = str(error)
    except Exception as error:
        status = "failed"
        message = str(error)

    return {
        "request_id": request_id,
        "ok": False,
        "status": status,
        "output": "",
        "error": message,
        "observed_at": utc_now(),
    }
