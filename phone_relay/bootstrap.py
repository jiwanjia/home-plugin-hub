"""One-time, privacy-preserving Termux bootstrap support."""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import tarfile
import threading
import time
from pathlib import Path
from typing import Tuple


BOOTSTRAP_ATTEMPTS = 10
PHONE_AGENT_FILES: Tuple[Tuple[str, str], ...] = (
    ("phone_relay/__init__.py", "phone_relay/__init__.py"),
    ("phone_relay/termux_command_runner.py", "phone_relay/termux_command_runner.py"),
    ("phone_relay/termux_executor.py", "phone_relay/termux_executor.py"),
    ("phone_relay/ui_reader.py", "phone_relay/ui_reader.py"),
    ("scripts/termux_phone_agent.py", "scripts/termux_phone_agent.py"),
)


class BootstrapUnavailable(ValueError):
    """Raised when no usable one-time bootstrap grant exists."""


class BootstrapCodeStore:
    def __init__(self, state_path: Path) -> None:
        self._state_path = state_path
        self._lock = threading.Lock()

    def claim(self, code: str) -> None:
        candidate_hash = hashlib.sha256(code.strip().encode("utf-8")).hexdigest()
        with self._lock:
            state = self._read_state()
            expires_at = float(state.get("expires_at", 0))
            attempts = int(state.get("attempts_remaining", 0))
            expected_hash = str(state.get("code_sha256", ""))
            if time.time() >= expires_at or attempts < 1:
                self._remove_state()
                raise BootstrapUnavailable("bootstrap grant is unavailable")
            if not hmac.compare_digest(candidate_hash, expected_hash):
                state["attempts_remaining"] = attempts - 1
                self._write_state(state)
                raise BootstrapUnavailable("bootstrap code is invalid")
            self._remove_state()

    def _read_state(self) -> dict:
        try:
            return json.loads(self._state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError) as error:
            raise BootstrapUnavailable("bootstrap grant is unavailable") from error

    def _write_state(self, state: dict) -> None:
        self._state_path.write_text(
            json.dumps(state, separators=(",", ":")),
            encoding="utf-8",
        )
        self._state_path.chmod(0o600)

    def _remove_state(self) -> None:
        self._state_path.unlink(missing_ok=True)


def installer_script(relay_url: str) -> str:
    archive_url = relay_url.rstrip("/") + "/api/phone-relay/bootstrap"
    return f"""#!/data/data/com.termux/files/usr/bin/sh
set -eu
archive="$(mktemp)"
cleanup() {{ rm -f "$archive"; }}
trap cleanup EXIT
printf 'Installation code: ' > /dev/tty
IFS= read -r code < /dev/tty
curl -fsS -H 'Content-Type: text/plain' --data-binary "$code" \\
  '{archive_url}' -o "$archive"
unset code
tar -xzf "$archive" -C "$HOME"
chmod 700 "$HOME/continuum-phone/start.sh"
chmod 600 "$HOME/continuum-phone/.relay-token"
printf 'Phone agent installed.\\n' > /dev/tty
"""


def build_phone_agent_archive(
    project_path: Path,
    relay_url: str,
    relay_token: str,
) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for source, destination in PHONE_AGENT_FILES:
            content = (project_path / source).read_bytes()
            _add_bytes(archive, f"continuum-phone/{destination}", content, 0o600)
        _add_bytes(
            archive,
            "continuum-phone/.relay-url",
            (relay_url.rstrip("/") + "\n").encode("utf-8"),
            0o600,
        )
        _add_bytes(
            archive,
            "continuum-phone/.relay-token",
            (relay_token + "\n").encode("utf-8"),
            0o600,
        )
        _add_bytes(
            archive,
            "continuum-phone/start.sh",
            _start_script().encode("utf-8"),
            0o700,
        )
    return buffer.getvalue()


def _start_script() -> str:
    return """#!/data/data/com.termux/files/usr/bin/sh
set -eu
app_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
export PHONE_RELAY_URL="$(cat "$app_dir/.relay-url")"
export PHONE_RELAY_TOKEN="$(cat "$app_dir/.relay-token")"
export PYTHONPATH="$app_dir"
exec python "$app_dir/scripts/termux_phone_agent.py"
"""


def _add_bytes(
    archive: tarfile.TarFile,
    name: str,
    content: bytes,
    mode: int,
) -> None:
    info = tarfile.TarInfo(name=name)
    info.size = len(content)
    info.mode = mode
    info.mtime = 0
    archive.addfile(info, io.BytesIO(content))
