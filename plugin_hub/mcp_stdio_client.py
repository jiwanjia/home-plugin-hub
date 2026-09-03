"""Persistent stdio MCP client owned by the Home Plugin Hub."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from typing import Any, Dict, List


MCP_PROTOCOL_VERSION = "2025-03-26"


class McpStdioError(RuntimeError):
    """Raised when an external MCP process cannot satisfy a request."""


class McpStdioClient:
    """Start one MCP child process and serialize requests over JSON lines."""

    def __init__(
        self,
        command: str,
        args: List[str],
        env_vars: List[str],
        timeout_seconds: float = 10,
    ):
        executable = sys.executable if command == "{python}" else command
        environment = os.environ.copy()
        missing = [name for name in env_vars if name not in environment]
        if missing:
            joined = ", ".join(missing)
            raise McpStdioError(f"缺少外部 MCP 环境变量: {joined}")

        self._timeout_seconds = timeout_seconds
        self._next_id = 1
        self._request_lock = threading.Lock()
        self._responses: queue.Queue[Dict[str, Any]] = queue.Queue()
        self._stderr_lines: queue.Queue[str] = queue.Queue(maxsize=20)
        self._process = subprocess.Popen(
            [executable, *args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=environment,
            creationflags=getattr(
                subprocess,
                "CREATE_NEW_PROCESS_GROUP",
                0,
            ),
        )
        self._stdout_thread = threading.Thread(
            target=self._read_stdout,
            name="home-mcp-stdout",
            daemon=True,
        )
        self._stderr_thread = threading.Thread(
            target=self._read_stderr,
            name="home-mcp-stderr",
            daemon=True,
        )
        self._stdout_thread.start()
        self._stderr_thread.start()
        self._initialize()

    def list_tools(self) -> List[Dict[str, Any]]:
        result = self._request("tools/list", {})
        tools = result.get("tools")
        if not isinstance(tools, list):
            raise McpStdioError("外部 MCP tools/list 未返回工具列表")
        return tools

    def call_tool(
        self,
        name: str,
        arguments: Dict[str, Any],
    ) -> Dict[str, Any]:
        return self._request(
            "tools/call",
            {
                "name": name,
                "arguments": arguments,
            },
        )

    def close(self) -> None:
        process = self._process
        if process.poll() is None:
            try:
                self._notify("notifications/cancelled", {})
            except (BrokenPipeError, OSError):
                pass
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        for stream in (
            process.stdin,
            process.stdout,
            process.stderr,
        ):
            if stream is not None:
                stream.close()

    def recent_error(self) -> str:
        lines = list(self._stderr_lines.queue)
        return "\n".join(lines[-5:])

    def _initialize(self) -> None:
        self._request(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {
                    "name": "home-plugin-hub",
                    "version": "1",
                },
            },
        )
        self._notify("notifications/initialized", {})

    def _request(
        self,
        method: str,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        with self._request_lock:
            request_id = self._next_id
            self._next_id += 1
            self._send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": params,
                }
            )
            while True:
                try:
                    response = self._responses.get(
                        timeout=self._timeout_seconds,
                    )
                except queue.Empty as exc:
                    detail = self.recent_error()
                    raise McpStdioError(
                        f"外部 MCP 请求超时: {method}; {detail}"
                    ) from exc
                if response.get("id") != request_id:
                    continue
                error = response.get("error")
                if isinstance(error, dict):
                    message = error.get("message", "未知 MCP 错误")
                    raise McpStdioError(str(message))
                result = response.get("result", {})
                if not isinstance(result, dict):
                    raise McpStdioError(
                        f"外部 MCP 返回了无效结果: {method}"
                    )
                return result

    def _notify(self, method: str, params: Dict[str, Any]) -> None:
        self._send(
            {
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
            }
        )

    def _send(self, payload: Dict[str, Any]) -> None:
        if self._process.poll() is not None:
            detail = self.recent_error()
            raise McpStdioError(
                f"外部 MCP 已退出 ({self._process.returncode}): {detail}"
            )
        stdin = self._process.stdin
        if stdin is None:
            raise McpStdioError("外部 MCP stdin 不可用")
        stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        stdin.flush()

    def _read_stdout(self) -> None:
        stdout = self._process.stdout
        if stdout is None:
            return
        for line in stdout:
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and "id" in payload:
                self._responses.put(payload)

    def _read_stderr(self) -> None:
        stderr = self._process.stderr
        if stderr is None:
            return
        for line in stderr:
            value = line.rstrip()
            if self._stderr_lines.full():
                try:
                    self._stderr_lines.get_nowait()
                except queue.Empty:
                    pass
            self._stderr_lines.put(value)
