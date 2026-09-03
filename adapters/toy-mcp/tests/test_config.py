"""测试配置加载和校验（Stage A — 无硬件）。"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from app.config import Settings, load_settings
from app.exceptions import ConfigError


class TestSettings:
    """Settings 类本身的单元测试。"""

    def test_defaults(self):
        """默认值检查。"""
        s = Settings(
            tuya_access_id="test-id",
            tuya_access_secret="test-secret",
            tuya_endpoint="https://openapi.tuyacn.com",  # 显式覆盖 .env
        )
        assert s.tuya_endpoint == "https://openapi.tuyacn.com"
        assert s.mcp_host == "127.0.0.1"
        assert s.mcp_port == 8765
        assert s.mcp_path == "/mcp"
        assert s.toy_command_cooldown_seconds == 2
        assert s.toy_max_routine_seconds == 120

    def test_endpoint_strips_trailing_slash(self):
        s = Settings(
            tuya_access_id="id",
            tuya_access_secret="secret",
            tuya_endpoint="https://example.com/",
        )
        assert s.tuya_endpoint == "https://example.com"

    def test_endpoint_must_be_https(self):
        with pytest.raises(Exception):
            Settings(
                tuya_access_id="id",
                tuya_access_secret="secret",
                tuya_endpoint="http://example.com",
            )

    def test_port_range_too_low(self):
        with pytest.raises(Exception):
            Settings(
                tuya_access_id="id",
                tuya_access_secret="secret",
                mcp_port=0,
            )

    def test_port_range_too_high(self):
        with pytest.raises(Exception):
            Settings(
                tuya_access_id="id",
                tuya_access_secret="secret",
                mcp_port=99999,
            )

    def test_validate_for_startup_missing_credentials(self):
        s = Settings(
            tuya_access_id="",
            tuya_access_secret="",
            tuya_endpoint="https://openapi.tuyacn.com",
        )
        issues = s.validate_for_startup()
        assert any("TUYA_ACCESS_ID" in i for i in issues)
        assert any("TUYA_ACCESS_SECRET" in i for i in issues)

    def test_validate_for_startup_has_credentials(self):
        s = Settings(
            tuya_access_id="test-id",
            tuya_access_secret="test-secret",
        )
        issues = s.validate_for_startup()
        assert len(issues) == 0

    def test_redacted_summary_never_leaks_secret(self):
        s = Settings(
            tuya_access_id="my-access-id-12345",
            tuya_access_secret="super-secret-key-abcde",
        )
        summary = s.redacted_summary()
        # Secret 绝对不能出现在摘要中
        assert "super-secret-key-abcde" not in str(summary)
        assert summary["tuya_access_secret"] == "(set)"
        # Access ID 部分脱敏
        assert "my-a" in summary["tuya_access_id"]
        assert "12345" not in summary["tuya_access_id"]

    def test_redacted_summary_empty_secret(self):
        s = Settings(
            tuya_access_id="",
            tuya_access_secret="",
            tuya_endpoint="https://openapi.tuyacn.com",
        )
        summary = s.redacted_summary()
        assert summary["tuya_access_secret"] == "(empty)"

    def test_cooldown_and_routine_bounds(self):
        """冷却和 routine 限制的边界。"""
        # 允许 0 冷却
        s = Settings(
            tuya_access_id="id",
            tuya_access_secret="secret",
            toy_command_cooldown_seconds=0,
        )
        assert s.toy_command_cooldown_seconds == 0

        # routine 最大 600 秒
        s = Settings(
            tuya_access_id="id",
            tuya_access_secret="secret",
            toy_max_routine_seconds=600,
        )
        assert s.toy_max_routine_seconds == 600

    def test_routine_over_max(self):
        with pytest.raises(Exception):
            Settings(
                tuya_access_id="id",
                tuya_access_secret="secret",
                toy_max_routine_seconds=999,
            )


class TestLoadSettings:
    """测试 load_settings 函数（需要 .env 文件）。"""

    def test_load_with_valid_env(self):
        """用临时 .env 测试完整加载。"""
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "TUYA_ACCESS_ID=test-id\n"
                "TUYA_ACCESS_SECRET=test-secret\n",
                encoding="utf-8",
            )
            s = load_settings(env_file=env_path)
            assert s.tuya_access_id == "test-id"

    def test_load_missing_credentials_raises(self):
        """缺少凭据时应当抛 ConfigError。"""
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("", encoding="utf-8")
            import os
            orig_cwd = os.getcwd()
            os.chdir(tmp)
            try:
                with pytest.raises(ConfigError):
                    load_settings()
            finally:
                os.chdir(orig_cwd)
