"""
MCP 插件: Python 代码执行
"""
import logging
from core.tool_base import MCPlugin, ToolResult
from mcp_plugins.python_repl_sessions import PythonReplSessionPool

logger = logging.getLogger(__name__)


class PythonPlugin(MCPlugin):
    def __init__(self, session_pool=None):
        self._session_pool = session_pool or PythonReplSessionPool()

    @property
    def name(self) -> str:
        return "run_python"

    @property
    def description(self) -> str:
        return (
            "执行 Python 代码，用于计算、数据处理、文件查询和快速验证。"
            "同一条回复内的多次调用会保留变量、函数和导入；回复结束后环境清空。"
            "最后一行表达式会像 Python REPL 一样直接返回结果。"
        )

    @property
    def parameters(self) -> dict:
        return {
            "code": {
                "type": "string",
                "description": "要在当前回复的 Python REPL 中执行的代码",
            }
        }

    def execute(self, code: str = "") -> ToolResult:
        """Keep callers without a reply scope on the historical one-shot path."""
        return self._execute(code, scope_id=None)

    def execute_with_context(self, arguments, host_context=None) -> ToolResult:
        code = arguments.get("code", "")
        context = host_context or {}
        scope_id = context.get("execution_scope_id")
        return self._execute(code, scope_id)

    def release_execution_scope(self, scope_id: str) -> None:
        self._session_pool.release(scope_id)

    def close(self) -> None:
        self._session_pool.close()

    def _execute(self, code, scope_id):
        logger.info("执行 Python: %s", code[:100])
        try:
            if scope_id:
                response = self._session_pool.execute(scope_id, code)
            else:
                response = self._session_pool.execute_once(code)
            if not response.get("ok"):
                return ToolResult.fail(
                    response.get("error", "Python 执行失败"),
                    operation="execute",
                )
            output = response.get("output", "")
            data = output[:3000] if output else "代码执行成功（无输出）"
            return ToolResult.success(data, operation="execute")
        except Exception as exc:
            return ToolResult.fail(str(exc), operation="execute")
