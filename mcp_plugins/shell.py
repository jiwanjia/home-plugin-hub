"""
MCP 插件: Shell 命令执行
"""
import subprocess
import logging
from core.tool_base import MCPlugin, ToolResult

logger = logging.getLogger(__name__)


class ShellPlugin(MCPlugin):
    @property
    def name(self) -> str:
        return "run_shell"

    @property
    def description(self) -> str:
        return "执行 Shell 命令（Windows PowerShell），用于文件操作、运行脚本、安装包等"

    @property
    def parameters(self) -> dict:
        return {
            "command": {
                "type": "string",
                "description": "要执行的 PowerShell 命令",
            }
        }

    def execute(self, command: str = "") -> ToolResult:
        logger.info(f"执行 Shell: {command[:100]}")
        try:
            result = subprocess.run(
                ["powershell", "-Command", command],
                capture_output=True, text=True, timeout=30
            )
            output = result.stdout or ""
            if result.stderr:
                output += f"\n[STDERR]\n{result.stderr}"
            if result.returncode != 0:
                output += f"\n[退出码: {result.returncode}]"

            ok = result.returncode == 0
            return ToolResult(
                ok=ok,
                data=output[:3000],
                error="" if ok else f"命令退出码: {result.returncode}",
                operation="execute",
            )
        except subprocess.TimeoutExpired:
            return ToolResult.fail("命令执行超时（30秒）", operation="execute")
        except Exception as e:
            return ToolResult.fail(str(e), operation="execute")
