"""
MCP 工具基类 — 所有插件继承此类
v2: 统一 ToolResult 返回格式 + 操作日志 + 可选 Sampling 预留
v3: 新增 ToolExecution 数据结构（供四阶段证据运行时 Tool Ledger 使用）
"""
import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional, List, Tuple


class ToolResult:
    """
    统一工具返回格式 — 所有插件必须通过此类返回结果。

    设计目标：
    1. 消除「看起来成功了」的歧义 —— ok 字段明确标记成功/失败
    2. 区分读/写/执行 —— operation 字段标注操作类型
    3. 追踪文件状态 —— path + timestamp 让模型知道「这个文件什么时候被操作过」
    4. 携带上下文提示 —— hints 字段可以在下次读取时注入「该文件 3 分钟前被修改过」
    """

    def __init__(
        self,
        ok: bool,
        data: str = "",
        error: str = "",
        operation: str = "",
        path: str = "",
        hints: Optional[List[str]] = None,
    ):
        self.ok = ok
        self.data = data
        self.error = error
        self.operation = operation   # "read" | "write" | "execute" | "search" | "list" | "delete"
        self.path = path             # 操作涉及的文件/目录路径（如有）
        self.timestamp = datetime.now().isoformat()
        self.hints = hints or []

    def to_dict(self) -> Dict:
        """完整结构化字典（供操作日志存储）"""
        return {
            "ok": self.ok,
            "operation": self.operation,
            "path": self.path,
            "timestamp": self.timestamp,
            "data": self.data[:500],       # 日志截断
            "error": self.error,
            "hints": self.hints,
        }

    def to_message(self) -> str:
        """
        返回给模型的文本 —— 结构化、可机读、无歧义。

        格式设计原则：
        - 第一行固定为 [OK] 或 [FAIL]，模型不用猜
        - 包含时间戳，模型可以判断时效性
        - 包含 operation 类型，模型知道这是读还是写
        - data 紧跟其后，清晰分隔
        """
        status = "[OK]" if self.ok else "[FAIL]"
        parts = [f"{status} {self.operation}"]

        if self.path:
            parts.append(f" | path: {self.path}")
        parts.append(f" | ts: {self.timestamp}")

        if self.error:
            parts.append(f"\n⚠️ 错误: {self.error}")

        if self.hints:
            for h in self.hints:
                parts.append(f"\n💡 {h}")

        if self.data:
            parts.append(f"\n--- 结果 ---\n{self.data}")

        return "".join(parts)

    @classmethod
    def success(cls, data: str, operation: str = "", path: str = "", hints: Optional[List[str]] = None) -> "ToolResult":
        """快捷构造成功结果"""
        return cls(ok=True, data=data, operation=operation, path=path, hints=hints)

    @classmethod
    def fail(cls, error: str, operation: str = "", path: str = "") -> "ToolResult":
        """快捷构造失败结果"""
        return cls(ok=False, error=error, operation=operation, path=path)


class MCPlugin(ABC):
    """MCP 工具插件基类 v2

    子类需要实现：
    - name: 工具名称
    - description: 工具描述
    - parameters: JSON Schema 参数定义
    - execute(**kwargs) -> ToolResult: 执行工具逻辑

    可选覆盖：
    - sample(prompt) -> ToolResult: 工具内 Sampling（需要 LLM 协助时调用）
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """工具名称（函数名）"""

    @property
    @abstractmethod
    def description(self) -> str:
        """工具描述"""

    @property
    @abstractmethod
    def parameters(self) -> Dict:
        """JSON Schema 格式的参数定义"""

    @abstractmethod
    def execute(self, **kwargs) -> ToolResult:
        """执行工具，必须返回 ToolResult"""

    def execute_with_context(
        self,
        arguments: Dict[str, Any],
        host_context: Optional[Dict[str, Any]] = None,
    ) -> ToolResult:
        """Execute with hidden host metadata while preserving old plugins."""
        del host_context
        return self.execute(**arguments)

    def release_execution_scope(self, scope_id: str) -> None:
        """Release reply-scoped resources; old plugins own none."""
        del scope_id
        return None

    def close(self) -> None:
        """Release plugin-owned background work when its host shuts down."""
        return None

    # ── 可选：Sampling 预留 ──
    # 将来某些插件（智能搜索、代码审查等）如果需要在工具内部请求 LLM 协助，
    # 可以调用 self.sample(prompt)。默认实现抛 NotImplementedError，
    # 子类覆盖即可。Registry 注入 _sample_fn 来打通模型调用链路。

    _sample_fn: Optional[Any] = None

    def sample(self, prompt: str) -> ToolResult:
        """
        [预留] 工具内 Sampling —— 在工具执行过程中请求 LLM 协助。

        用法（需要此能力的插件覆盖此方法或使用注入的 _sample_fn）：
            result = self.sample("帮我从这 100 条结果中挑出最相关的 5 条")
        """
        if self._sample_fn:
            return self._sample_fn(prompt)
        raise NotImplementedError(
            f"工具 [{self.name}] 未启用 Sampling 能力。"
            "如需使用，请在 Registry 中注入 _sample_fn。"
        )

    def to_openai_tool(self) -> Dict:
        """转换为 OpenAI Function Calling 格式。

        参数 required 由 execute() 方法签名自动推导：
        - 没有默认值的参数 → required
        - 有默认值的参数 → optional
        这样无需手动在每个参数定义里加 "required": True。
        """
        import inspect
        try:
            sig = inspect.signature(self.execute)
            required_params = [
                name for name, param in sig.parameters.items()
                if param.default is inspect.Parameter.empty
                and name not in ('self', 'kwargs')
            ]
        except Exception:
            required_params = []

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.parameters,
                    "required": required_params,
                },
            },
        }


# ═══════════════════════════════════════════════════════════
#  ToolExecution — 工具执行证据（四阶段运行时 §3.1）
# ═══════════════════════════════════════════════════════════

@dataclass(frozen=True)
class ToolExecution:
    """一次真实的工具调用记录。

    由 ToolLedger 管理，只能通过 execute_recorded() 产生。
    status 只能是 succeeded / failed / cancelled。
    """
    turn_id: str
    call_id: str
    tool_name: str
    arguments_sha256: str
    status: str          # "succeeded" | "failed" | "cancelled"
    started_at: str
    completed_at: str
    result_sha256: Optional[str] = None
    evidence_refs: Tuple[str, ...] = ()
    error_code: Optional[str] = None

    @classmethod
    def from_result(
        cls,
        turn_id: str,
        call_id: str,
        tool_name: str,
        arguments: str,
        result: "ToolResult",
        started_at: str,
    ) -> "ToolExecution":
        """从 ToolResult 构造 ToolExecution。"""
        args_hash = hashlib.sha256(arguments.encode("utf-8")).hexdigest()[:16]
        status = "succeeded" if result.ok else "failed"
        result_hash = hashlib.sha256(
            (result.data + result.error).encode("utf-8")
        ).hexdigest()[:16] if (result.data or result.error) else None
        return cls(
            turn_id=turn_id,
            call_id=call_id,
            tool_name=tool_name,
            arguments_sha256=args_hash,
            status=status,
            started_at=started_at,
            completed_at=datetime.now().isoformat(),
            result_sha256=result_hash,
            error_code=result.error if not result.ok else None,
        )
