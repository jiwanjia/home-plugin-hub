"""Toy MCP 配置 —— 从 .env 加载，启动时校验。

不在此模块中连接 Tuya Cloud，只做静态校验。
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_env() -> Path | None:
    """查找 .env 文件：优先当前目录，其次项目根。"""
    candidates = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parent.parent / ".env",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


class Settings(BaseSettings):
    """Toy MCP 配置。

    所有字段都可以通过环境变量或 .env 文件设置。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Tuya Cloud ────────────────────────────────────

    tuya_access_id: str = Field(
        default="",
        description="Tuya 云项目 Access ID",
    )
    tuya_access_secret: str = Field(
        default="",
        description="Tuya 云项目 Access Secret",
    )
    tuya_endpoint: str = Field(
        default="https://openapi.tuyacn.com",
        description="Tuya API endpoint",
    )

    # ── 红外设备 ──────────────────────────────────────

    tuya_infrared_id: str = Field(
        default="",
        description="红外遥控器设备 ID",
    )
    tuya_remote_id: str = Field(
        default="",
        description="DIY 遥控器 ID",
    )

    # ── 学习码 ────────────────────────────────────────

    toy_power_code: str = Field(default="", description="电源键学习码")
    toy_pat_code: str = Field(default="", description="拍打键学习码")
    toy_slow_code: str = Field(default="", description="减速键学习码")
    toy_fast_code: str = Field(default="", description="加速键学习码")

    # ── MCP Server ────────────────────────────────────

    mcp_host: str = Field(default="127.0.0.1", description="MCP 监听地址")
    mcp_port: int = Field(default=8765, description="MCP 监听端口")
    mcp_path: str = Field(default="/mcp", description="MCP Streamable HTTP 路径")

    # ── 安全限制 ──────────────────────────────────────

    toy_command_cooldown_seconds: int = Field(
        default=2, ge=0, description="命令冷却时间（秒）"
    )
    toy_max_routine_seconds: int = Field(
        default=120, ge=1, le=600, description="routine 最大执行时间（秒）"
    )
    log_level: str = Field(default="INFO", description="日志级别")

    # ── 校验 ──────────────────────────────────────────

    @field_validator("tuya_endpoint")
    @classmethod
    def _endpoint_must_be_https(cls, v: str) -> str:
        if not v.startswith("https://"):
            raise ValueError(f"TUYA_ENDPOINT must start with https://, got: {v}")
        return v.rstrip("/")

    @field_validator("mcp_host")
    @classmethod
    def _host_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("MCP_HOST must not be empty")
        return v.strip()

    @field_validator("mcp_port")
    @classmethod
    def _port_range(cls, v: int) -> int:
        if not (1 <= v <= 65535):
            raise ValueError(f"MCP_PORT out of range: {v}")
        return v

    def validate_for_startup(self) -> list[str]:
        """启动时运行，返回所有配置问题。

        Returns:
            字符串列表，空列表 = 无问题。
        """
        issues: list[str] = []

        if not self.tuya_access_id:
            issues.append("TUYA_ACCESS_ID is required")
        if not self.tuya_access_secret:
            issues.append("TUYA_ACCESS_SECRET is required")

        # 红外设备 ID 和遥控器 ID 在发现阶段后才需要，
        # 这里只做格式提示，不强制非空。
        return issues

    # ── 脱敏显示 ──────────────────────────────────────

    def redacted_summary(self) -> dict:
        """返回脱敏后的配置摘要，可安全打印到日志。"""
        def _mask(s: str, keep: int = 4) -> str:
            if len(s) <= keep:
                return "***"
            return s[:keep] + "***" + s[-4:] if len(s) > keep * 2 else s[:keep] + "***"

        return {
            "tuya_access_id": _mask(self.tuya_access_id) if self.tuya_access_id else "(empty)",
            "tuya_access_secret": "(set)" if self.tuya_access_secret else "(empty)",
            "tuya_endpoint": self.tuya_endpoint,
            "tuya_infrared_id": self.tuya_infrared_id or "(not set)",
            "tuya_remote_id": self.tuya_remote_id or "(not set)",
            "mcp_host": self.mcp_host,
            "mcp_port": self.mcp_port,
            "mcp_path": self.mcp_path,
            "cooldown_s": self.toy_command_cooldown_seconds,
            "max_routine_s": self.toy_max_routine_seconds,
            "log_level": self.log_level,
        }


def load_settings(env_file: Path | str | None = None) -> Settings:
    """从环境变量/.env 加载配置并做启动校验。

    Raises:
        ConfigError: 配置有严重问题。
    """
    # 自动寻找 .env
    if env_file is None:
        env_file = _find_env() or ".env"

    try:
        settings = Settings(_env_file=env_file)  # type: ignore[call-arg]
    except Exception as exc:
        from .exceptions import ConfigError
        raise ConfigError(f"Failed to load settings: {exc}") from exc

    issues = settings.validate_for_startup()
    if issues:
        from .exceptions import ConfigError
        raise ConfigError("Configuration errors:\n" + "\n".join(f"  - {i}" for i in issues))

    return settings
