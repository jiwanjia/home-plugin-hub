"""Toy MCP 自定义异常。

所有异常都继承自 ToyMCPError，方便上层统一捕获。
"""


class ToyMCPError(Exception):
    """Toy MCP 基础异常。"""


# ── 配置 ──────────────────────────────────────────────

class ConfigError(ToyMCPError):
    """配置错误：缺少必需的环境变量或值不合法。"""


# ── Tuya ──────────────────────────────────────────────

class TuyaError(ToyMCPError):
    """Tuya 相关错误的基类。"""


class TuyaAuthError(TuyaError):
    """Tuya 认证失败：Access ID/Secret 无效，或 token 刷新失败。"""


class TuyaAPIError(TuyaError):
    """Tuya API 参数/业务错误 —— 不重试。"""


class TuyaNetworkError(TuyaError):
    """Tuya 网络/临时错误 —— 可重试。"""


class TuyaRegionError(TuyaError):
    """Tuya 跨区访问错误：数据中心不匹配。"""


# ── Toy Service ───────────────────────────────────────

class ToyServiceError(ToyMCPError):
    """玩偶服务运行时错误。"""


class ToyCooldownError(ToyServiceError):
    """命令冷却中，拒绝重复调用。"""


class ToyRoutineBusyError(ToyServiceError):
    """已有 routine 在运行，拒绝并发调用。"""


class ToyRoutineTimeoutError(ToyServiceError):
    """Routine 执行超时。"""


class ToyRoutineStepError(ToyServiceError):
    """Routine failed after one or more commands were already sent."""

    def __init__(self, completed_steps: list[str], cause: Exception) -> None:
        self.completed_steps = list(completed_steps)
        self.cause = cause
        completed = ", ".join(self.completed_steps) or "none"
        super().__init__(
            f"Routine failed after steps [{completed}]: {cause}"
        )


# ── Air Conditioner Service ──────────────────────────────

class AirConditionerServiceError(ToyMCPError):
    """Air-conditioner discovery, state, or command error."""
