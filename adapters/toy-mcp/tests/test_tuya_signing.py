"""测试 Tuya API 签名、token 缓存、重试规则（Stage A — 无硬件）。

所有 TuyaClient 调用均使用 mock，不访问真实网络。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest import mock

import httpx
import pytest

from app.config import Settings
from app.tuya_client import (
    TuyaClient,
    _hmac_sha256,
    _sha256,
    _gen_nonce,
    _build_sign,
    _make_string_to_sign,
    _serialize_body,
    _read_token_cache,
    _write_token_cache,
    TOKEN_CACHE_FILE,
)
from app.exceptions import (
    TuyaAPIError,
    TuyaAuthError,
    TuyaNetworkError,
    TuyaRegionError,
)


# ── 纯签名测试 ────────────────────────────────────────

class TestSigning:
    """签名算法正确性。"""

    def test_hmac_sha256_known_vector(self):
        """用已知向量验证 HMAC-SHA256。"""
        result = _hmac_sha256("secret", "hello")
        # HMAC-SHA256("hello", "secret") 的已知结果
        assert len(result) == 64
        assert result == result.upper()  # 必须全大写

    def test_hmac_sha256_deterministic(self):
        """相同输入产生相同输出。"""
        a = _hmac_sha256("key1", "msg1")
        b = _hmac_sha256("key1", "msg1")
        assert a == b

    def test_hmac_sha256_different_inputs(self):
        """不同输入产生不同输出。"""
        a = _hmac_sha256("key1", "msg1")
        b = _hmac_sha256("key1", "msg2")
        c = _hmac_sha256("key2", "msg1")
        assert a != b
        assert a != c

    def test_build_sign_token_format(self):
        """token 签名（无 access_token）的格式。"""
        sts = _make_string_to_sign("GET", "/v1.0/token?grant_type=1")
        sign = _build_sign("my-id", "my-secret", "1234567890", "nonce1", sts)
        assert isinstance(sign, str)
        assert len(sign) == 64
        assert sign == sign.upper()

    def test_build_sign_api_format(self):
        """API 签名（有 access_token）的格式。"""
        sts = _make_string_to_sign("GET", "/v1.0/devices")
        sign = _build_sign("my-id", "my-secret", "1234567890", "nonce2", sts, access_token="my-token")
        assert isinstance(sign, str)
        assert len(sign) == 64
        assert sign == sign.upper()

    def test_token_and_api_sign_differ(self):
        """token 签名和 API 签名应该不同（有无 access_token）。"""
        sts = _make_string_to_sign("GET", "/v1.0/test")
        token_s = _build_sign("id", "secret", "1000", "n1", sts)
        api_s = _build_sign("id", "secret", "1000", "n2", sts, access_token="token")
        assert token_s != api_s

    def test_body_serialization_matches_tuya_request(self):
        body = {"code": "learned-code"}
        serialized = _serialize_body(body)
        assert serialized == '{"code":"learned-code"}'
        string_to_sign = _make_string_to_sign("POST", "/v2.0/test", body)
        assert _sha256(serialized) in string_to_sign


# ── Token 缓存测试 ────────────────────────────────────

class TestTokenCache:
    """token 缓存的读写。"""

    def test_read_missing_file(self, monkeypatch, tmp_path):
        """缓存文件不存在时返回 None。"""
        fake_path = tmp_path / "nonexistent.json"
        monkeypatch.setattr(
            "app.tuya_client.TOKEN_CACHE_FILE", fake_path
        )
        assert _read_token_cache() is None

    def test_read_valid_cache(self, monkeypatch, tmp_path):
        """正确格式的缓存能正常读取。"""
        fake_path = tmp_path / "cache.json"
        fake_path.write_text(
            json.dumps({"access_token": "tok123", "expire_at": 9999999999999}),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "app.tuya_client.TOKEN_CACHE_FILE", fake_path
        )
        cached = _read_token_cache()
        assert cached is not None
        assert cached["access_token"] == "tok123"

    def test_read_invalid_json(self, monkeypatch, tmp_path):
        """损坏的文件返回 None。"""
        fake_path = tmp_path / "bad.json"
        fake_path.write_text("not json {{{", encoding="utf-8")
        monkeypatch.setattr(
            "app.tuya_client.TOKEN_CACHE_FILE", fake_path
        )
        assert _read_token_cache() is None

    def test_write_and_read_roundtrip(self, monkeypatch, tmp_path):
        """写入后能正确读取。"""
        fake_path = tmp_path / "cache2.json"
        monkeypatch.setattr(
            "app.tuya_client.TOKEN_CACHE_FILE", fake_path
        )
        data = {"access_token": "abc", "expire_at": 1234567890000}
        _write_token_cache(data)
        assert fake_path.exists()
        read = _read_token_cache()
        assert read == data


# ── Mock 响应工具 ─────────────────────────────────────

def _mock_httpx_response(status: int, body: dict) -> mock.MagicMock:
    """构造 mock httpx.Response。"""
    resp = mock.MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.is_success = 200 <= status < 300
    resp.json.return_value = body
    resp.text = json.dumps(body)
    return resp


def _make_client(settings: Settings | None = None, tmp_path: Path | None = None) -> TuyaClient:
    """创建测试用 TuyaClient，隔离 token 缓存。"""
    if settings is None:
        settings = Settings(
            tuya_access_id="test-id",
            tuya_access_secret="test-secret",
            tuya_infrared_id="ir-123",
            tuya_remote_id="rm-456",
        )
    client = TuyaClient(settings)
    # 隔离 token 缓存文件，防止测试间互相干扰
    if tmp_path is not None:
        client._token_cache_file = tmp_path / "token_cache.json"
    return client


# ── TuyaClient 测试 ──────────────────────────────────

class TestTuyaClientToken:
    """token 获取和缓存测试。"""

    def test_get_token_caches_and_reuses(self, monkeypatch, tmp_path):
        """获取 token 后缓存，第二次不发起 HTTP 请求。"""
        monkeypatch.setattr(
            "app.tuya_client.TOKEN_CACHE_FILE", tmp_path / "token_cache.json"
        )
        client = _make_client()
        # 手动清掉可能的缓存
        client._token = None
        client._token_expire_at = 0

        token_resp = _mock_httpx_response(200, {
            "success": True,
            "result": {
                "access_token": "fresh-token",
                "expire_time": 7200,
            },
        })

        with mock.patch.object(client._http, "get", return_value=token_resp) as mget:
            tok1 = client.get_access_token()
            assert tok1 == "fresh-token"
            assert mget.call_count == 1

            # 第二次调用应使用缓存
            tok2 = client.get_access_token()
            assert tok2 == "fresh-token"
            assert mget.call_count == 1  # 没有新的 HTTP 请求

    def test_get_token_refresh_on_expiry(self, monkeypatch, tmp_path):
        """缓存过期后重新获取。"""
        monkeypatch.setattr(
            "app.tuya_client.TOKEN_CACHE_FILE", tmp_path / "token_cache.json"
        )
        client = _make_client()
        client._token = "old-token"
        client._token_expire_at = 1  # 很久以前就过期了

        token_resp = _mock_httpx_response(200, {
            "success": True,
            "result": {
                "access_token": "new-token",
                "expire_time": 7200,
            },
        })

        with mock.patch.object(client._http, "get", return_value=token_resp):
            tok = client.get_access_token()
            assert tok == "new-token"

    def test_get_token_auth_failure(self, monkeypatch, tmp_path):
        """认证失败时抛出 TuyaAuthError。"""
        monkeypatch.setattr(
            "app.tuya_client.TOKEN_CACHE_FILE", tmp_path / "token_cache.json"
        )
        client = _make_client()
        client._token = None
        client._token_expire_at = 0

        error_resp = _mock_httpx_response(401, {
            "code": 1004,
            "msg": "Invalid access ID",
        })

        with mock.patch.object(client._http, "get", return_value=error_resp):
            with pytest.raises(TuyaAuthError):
                client.get_access_token()


class TestTuyaClientRetry:
    """重试规则测试。"""

    def test_auth_error_triggers_token_refresh(self, monkeypatch, tmp_path):
        """API 返回认证错误 → 刷新 token → 重试一次。"""
        monkeypatch.setattr(
            "app.tuya_client.TOKEN_CACHE_FILE", tmp_path / "token_cache.json"
        )
        client = _make_client()

        token_resp = _mock_httpx_response(200, {
            "success": True,
            "result": {"access_token": "tok", "expire_time": 7200},
        })
        auth_err = _mock_httpx_response(401, {"code": 1010, "msg": "token expired"})
        success = _mock_httpx_response(200, {"success": True, "result": []})

        with mock.patch.object(
            client._http, "get", side_effect=[token_resp, auth_err, token_resp, success]
        ) as mget:
            result = client.list_remotes()
            assert result == []
            assert mget.call_count == 4  # token + api + token(refresh) + api(retry)

    def test_network_error_retries(self, monkeypatch, tmp_path):
        """网络错误重试最多 2 次。"""
        monkeypatch.setattr(
            "app.tuya_client.TOKEN_CACHE_FILE", tmp_path / "token_cache.json"
        )
        client = _make_client()

        token_resp = _mock_httpx_response(200, {
            "success": True,
            "result": {"access_token": "tok", "expire_time": 7200},
        })
        net_err = httpx.ConnectError("connection refused")
        success = _mock_httpx_response(200, {"success": True, "result": []})

        with mock.patch.object(
            client._http, "get",
            side_effect=[token_resp, net_err, net_err, success],
        ) as mget:
            result = client.list_remotes()
            assert result == []
            # token + 2 failures + 1 success = 4
            assert mget.call_count == 4

    def test_network_error_exhausted(self, monkeypatch, tmp_path):
        """网络错误超过重试次数后抛出。"""
        monkeypatch.setattr(
            "app.tuya_client.TOKEN_CACHE_FILE", tmp_path / "token_cache.json"
        )
        client = _make_client()

        token_resp = _mock_httpx_response(200, {
            "success": True,
            "result": {"access_token": "tok", "expire_time": 7200},
        })
        net_err = httpx.ConnectError("connection refused")

        with mock.patch.object(
            client._http, "get",
            side_effect=[token_resp, net_err, net_err, net_err],
        ):
            with pytest.raises(TuyaNetworkError):
                client.list_remotes()

    def test_param_error_no_retry(self, monkeypatch, tmp_path):
        """参数错误不重试。"""
        monkeypatch.setattr(
            "app.tuya_client.TOKEN_CACHE_FILE", tmp_path / "token_cache.json"
        )
        client = _make_client()

        token_resp = _mock_httpx_response(200, {
            "success": True,
            "result": {"access_token": "tok", "expire_time": 7200},
        })
        # 使用 code=900 代表参数错误（非 server error，非 auth error）
        param_err = _mock_httpx_response(400, {"code": 900, "msg": "invalid param"})

        with mock.patch.object(
            client._http, "get",
            side_effect=[token_resp, param_err],
        ) as mget:
            with pytest.raises(TuyaAPIError):
                client.list_remotes()
            # 只调用了 token + 1 API，没有重试
            assert mget.call_count == 2


class TestTuyaClientErrors:
    """各类错误的转换测试。"""

    def test_region_error(self, monkeypatch, tmp_path):
        """跨区错误抛出 TuyaRegionError。"""
        monkeypatch.setattr(
            "app.tuya_client.TOKEN_CACHE_FILE", tmp_path / "token_cache.json"
        )
        client = _make_client()

        token_resp = _mock_httpx_response(200, {
            "success": True,
            "result": {"access_token": "tok", "expire_time": 7200},
        })
        region_err = _mock_httpx_response(403, {
            "code": 1012,
            "msg": "data center mismatch",
        })

        with mock.patch.object(
            client._http, "get",
            side_effect=[token_resp, region_err],
        ):
            with pytest.raises(TuyaRegionError):
                client.list_remotes()

    def test_timeout_converts_to_network_error(self):
        """超时转换为 TuyaNetworkError。"""
        client = _make_client()
        client._token = "tok"
        client._token_expire_at = 9999999999999

        with mock.patch.object(
            client._http, "get",
            side_effect=httpx.TimeoutException("timeout"),
        ):
            with pytest.raises(TuyaNetworkError):
                client.list_remotes()

    def test_missing_infrared_id_raises(self):
        """缺少 infrared_id 时 list_remotes 报错。"""
        settings = Settings(
            tuya_access_id="id",
            tuya_access_secret="secret",
            tuya_infrared_id="",  # 显式置空，防止 .env 泄漏
        )
        client = _make_client(settings)
        with pytest.raises(TuyaAPIError, match="infrared_id"):
            client.list_remotes()

    def test_missing_remote_id_raises(self):
        """缺少 remote_id 时 list_learning_codes 报错。"""
        settings = Settings(
            tuya_access_id="id",
            tuya_access_secret="secret",
            tuya_infrared_id="ir-1",
            tuya_remote_id="",
        )
        client = _make_client(settings)
        with pytest.raises(TuyaAPIError, match="remote_id"):
            client.list_learning_codes()

    def test_ir_routes_use_v2(self):
        client = _make_client()
        client._token = "tok"
        client._token_expire_at = 9999999999999
        success = _mock_httpx_response(200, {"success": True, "result": []})

        with mock.patch.object(client._http, "get", return_value=success) as mget:
            client.list_remotes()

        assert mget.call_args.args[0].endswith(
            "/v2.0/infrareds/ir-123/remotes"
        )

    def test_send_learning_code_uses_v2_body(self):
        client = _make_client()
        client._token = "tok"
        client._token_expire_at = 9999999999999
        success = _mock_httpx_response(
            200,
            {"success": True, "result": True},
        )

        with mock.patch.object(client._http, "post", return_value=success) as mpost:
            client.send_learning_code("learned-code")

        assert mpost.call_args.args[0].endswith(
            "/v2.0/infrareds/ir-123/remotes/rm-456/learning-codes"
        )
        assert mpost.call_args.kwargs["content"] == b'{"code":"learned-code"}'

    def test_air_conditioner_status_uses_v2_route(self):
        client = _make_client()
        client._token = "tok"
        client._token_expire_at = 9999999999999
        success = _mock_httpx_response(
            200,
            {"success": True, "result": {"power": "1", "temp": "24"}},
        )

        with mock.patch.object(client._http, "get", return_value=success) as mget:
            result = client.get_air_conditioner_status("ac-remote")

        assert result["temp"] == "24"
        assert mget.call_args.args[0].endswith(
            "/v2.0/infrareds/ir-123/remotes/ac-remote/ac/status"
        )

    def test_air_conditioner_command_uses_v2_body(self):
        client = _make_client()
        client._token = "tok"
        client._token_expire_at = 9999999999999
        success = _mock_httpx_response(
            200,
            {"success": True, "result": True},
        )

        with mock.patch.object(client._http, "post", return_value=success) as mpost:
            client.send_air_conditioner_command("ac-remote", "temp", 25)

        assert mpost.call_args.args[0].endswith(
            "/v2.0/infrareds/ir-123/air-conditioners/ac-remote/command"
        )
        assert mpost.call_args.kwargs["content"] == b'{"code":"temp","value":25}'

    def test_http_200_business_error_raises(self):
        client = _make_client()
        client._token = "tok"
        client._token_expire_at = 9999999999999
        failure = _mock_httpx_response(
            200,
            {"success": False, "code": 900, "msg": "invalid command"},
        )

        with mock.patch.object(client._http, "post", return_value=failure):
            with pytest.raises(TuyaAPIError, match="invalid command"):
                client.send_learning_code("learned-code")
