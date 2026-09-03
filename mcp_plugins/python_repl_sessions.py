"""Own reply-scoped Python worker processes for the run_python plugin."""

import json
import queue
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PythonReplSession:
    """Serialize requests to one isolated Python namespace process."""

    def __init__(self, timeout_seconds=60):
        self._timeout_seconds = timeout_seconds
        self._lock = threading.Lock()
        self.last_used = time.monotonic()
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._process = subprocess.Popen(
            [sys.executable, "-m", "mcp_plugins.python_repl_worker"],
            cwd=str(PROJECT_ROOT),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creation_flags,
        )

    def execute(self, code):
        with self._lock:
            if self._process.poll() is not None:
                raise RuntimeError("Python REPL 子进程已意外退出，变量环境已重置")
            request_id = uuid.uuid4().hex
            request = json.dumps(
                {"id": request_id, "code": code},
                ensure_ascii=False,
            )
            self._process.stdin.write(request + "\n")
            self._process.stdin.flush()
            response = self._read_response(self._timeout_seconds)
            self.last_used = time.monotonic()
            if response.get("id") != request_id:
                raise RuntimeError("Python REPL 返回了不匹配的响应")
            return response

    def close(self):
        with self._lock:
            process = self._process
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()

    def _read_response(self, timeout_seconds):
        responses = queue.Queue(maxsize=1)

        def read_line():
            responses.put(self._process.stdout.readline())

        reader = threading.Thread(target=read_line, daemon=True)
        reader.start()
        try:
            line = responses.get(timeout=timeout_seconds)
        except queue.Empty as exc:
            raise TimeoutError(
                "Python 代码运行超过 60 秒，子进程已终止，变量环境已重置"
            ) from exc
        if not line:
            stderr = self._process.stderr.read().strip()
            detail = f": {stderr[-500:]}" if stderr else ""
            raise RuntimeError(
                "Python REPL 子进程已意外退出，变量环境已重置" + detail
            )
        return json.loads(line)


class PythonReplSessionPool:
    """Map hidden reply scope IDs to workers and reclaim idle sessions."""

    def __init__(self, timeout_seconds=60, idle_seconds=600):
        self._timeout_seconds = timeout_seconds
        self._idle_seconds = idle_seconds
        self._lock = threading.Lock()
        self._sessions = {}
        self._closed = threading.Event()
        self._janitor = threading.Thread(target=self._reclaim_idle, daemon=True)
        self._janitor.start()

    def execute(self, scope_id, code):
        session = self._session(scope_id)
        try:
            return session.execute(code)
        except (TimeoutError, RuntimeError, OSError, json.JSONDecodeError):
            self.release(scope_id)
            raise

    def execute_once(self, code):
        session = PythonReplSession(self._timeout_seconds)
        try:
            return session.execute(code)
        finally:
            session.close()

    def release(self, scope_id):
        with self._lock:
            session = self._sessions.pop(scope_id, None)
        if session is not None:
            session.close()

    def close(self):
        self._closed.set()
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            session.close()

    def _session(self, scope_id):
        with self._lock:
            session = self._sessions.get(scope_id)
            if session is None:
                session = PythonReplSession(self._timeout_seconds)
                self._sessions[scope_id] = session
            return session

    def _reclaim_idle(self):
        interval = min(60, max(1, self._idle_seconds / 2))
        while not self._closed.wait(interval):
            self.reclaim_idle_sessions()

    def reclaim_idle_sessions(self, now=None):
        """Reclaim stale workers; the explicit clock keeps this testable."""
        current_time = now if now is not None else time.monotonic()
        with self._lock:
            expired = [
                scope_id
                for scope_id, session in self._sessions.items()
                if current_time - session.last_used >= self._idle_seconds
            ]
        for scope_id in expired:
            self.release(scope_id)
