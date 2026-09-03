"""Exchange the current hidden Flask reply scope with a stdio bridge."""

import json
import os
from pathlib import Path


STATE_PATH_ENV = "HOME_EXECUTION_SCOPE_STATE"


def write_execution_scope(path, scope_id):
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = state_path.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps({"execution_scope_id": scope_id}),
        encoding="utf-8",
    )
    os.replace(temporary_path, state_path)


def clear_execution_scope(path, scope_id):
    state_path = Path(path)
    current_scope = read_execution_scope(state_path)
    if current_scope == scope_id:
        state_path.unlink(missing_ok=True)


def read_execution_scope(path=None):
    raw_path = path or os.getenv(STATE_PATH_ENV, "")
    if not raw_path:
        return None
    try:
        payload = json.loads(Path(raw_path).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    scope_id = payload.get("execution_scope_id")
    return scope_id if isinstance(scope_id, str) and scope_id else None
