"""Tuya Cloud API 客户端。

职责：
- 获取 & 缓存 access token
- HMAC-SHA256 请求签名
- 发现设备 / 遥控器 / 学习码
- 发送红外学习码
- 超时、重试、错误转换

不负责：
- 冷却计时（toy_service.py）
- 并发锁（toy_service.py）
- 审计日志（toy_service.py）
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from pathlib import Path

import httpx

from .config import Settings
from .exceptions import (
    TuyaAPIError,
    TuyaAuthError,
    TuyaNetworkError,
    TuyaRegionError,
)

logger = logging.getLogger("toy-mcp.tuya")

# ── 常量 ──────────────────────────────────────────────

TOKEN_CACHE_FILE: Path = Path(__file__).resolve().parent.parent / "data" / "token_cache.json"
TOKEN_REFRESH_MARGIN: int = 120  # token 过期前多少秒就刷新
HTTP_TIMEOUT: float = 10.0
MAX_NETWORK_RETRIES: int = 2
MAX_AUTH_RETRIES: int = 1  # 刷新 token 后只重试 1 次

TOKEN_API_PREFIX: str = "/v1.0"
DEVICE_API_PREFIX: str = "/v1.0"
IR_API_PREFIX: str = "/v2.0"


def _now_ms() -> int:
    """当前时间戳（毫秒）。"""
    return int(time.time() * 1000)


# ── Token 缓存 ────────────────────────────────────────

def _read_token_cache() -> dict | None:
    """读取缓存的 token，如果文件不存在或格式不对返回 None。"""
    if not TOKEN_CACHE_FILE.exists():
        return None
    try:
        data = json.loads(TOKEN_CACHE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "access_token" in data and "expire_at" in data:
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return None


def _write_token_cache(data: dict) -> None:
    """原子写入 token 缓存。"""
    tmp = TOKEN_CACHE_FILE.with_suffix(".tmp")
    TOKEN_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(TOKEN_CACHE_FILE)


# ── 签名（Tuya 新签名机制，post-2021）───────────────

# SHA256 空字符串
_SHA256_EMPTY = (
    "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
)


def _sha256(content: str) -> str:
    """SHA256 hex 小写。"""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _hmac_sha256(key: str, message: str) -> str:
    """HMAC-SHA256，返回大写 hex 字符串。"""
    mac = hmac.new(key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256)
    return mac.hexdigest().upper()


def _gen_nonce() -> str:
    """生成随机 nonce。"""
    import uuid
    return str(uuid.uuid4())


def _build_sign(
    access_id: str,
    access_secret: str,
    timestamp: str,
    nonce: str,
    string_to_sign: str,
    access_token: str | None = None,
) -> str:
    """Tuya 新签名机制。

    Token 请求: sign = HMAC-SHA256(client_id + t + nonce + stringToSign, secret)
    服务请求:   sign = HMAC-SHA256(client_id + access_token + t + nonce + stringToSign, secret)
    """
    if access_token:
        payload = access_id + access_token + timestamp + nonce + string_to_sign
    else:
        payload = access_id + timestamp + nonce + string_to_sign
    return _hmac_sha256(access_secret, payload)


def _serialize_body(body: dict | None) -> str:
    """Serialize a request body exactly as it will be sent."""
    if body is None:
        return ""
    return json.dumps(
        body,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def _make_string_to_sign(method: str, path: str, body: dict | None = None) -> str:
    """构建 stringToSign。

    格式: METHOD\nSHA256(body)\n\npath
    """
    body_str = _serialize_body(body)
    body_hash = _sha256(body_str)
    return f"{method.upper()}\n{body_hash}\n\n{path}"


# ── Client ────────────────────────────────────────────

class TuyaClient:
    """Tuya Cloud API 客户端。"""

    def __init__(self, settings: Settings) -> None:
        self._access_id = settings.tuya_access_id
        self._access_secret = settings.tuya_access_secret
        self._endpoint = settings.tuya_endpoint
        self._infrared_id = settings.tuya_infrared_id
        self._remote_id = settings.tuya_remote_id
        self._token: str | None = None
        self._token_expire_at: int = 0
        self._http = httpx.Client(timeout=HTTP_TIMEOUT)

    # ── Token ──────────────────────────────────────

    def get_access_token(self) -> str:
        """获取有效 access token（优先用缓存）。"""
        # 检查缓存
        if not self._token:
            cached = _read_token_cache()
            if cached:
                self._token = cached["access_token"]
                self._token_expire_at = cached.get("expire_at", 0)

        now = _now_ms()
        # 留出缓冲，提前刷新
        if self._token and now < (self._token_expire_at - TOKEN_REFRESH_MARGIN * 1000):
            logger.debug("Using cached access token")
            return self._token

        # 获取新 token（使用 Tuya 新签名机制）
        logger.info("Fetching new access token")
        timestamp = str(_now_ms())
        nonce = _gen_nonce()
        token_path = f"{TOKEN_API_PREFIX}/token?grant_type=1"
        string_to_sign = _make_string_to_sign("GET", token_path)
        sign = _build_sign(
            self._access_id, self._access_secret,
            timestamp, nonce, string_to_sign,
        )

        headers = {
            "client_id": self._access_id,
            "sign": sign,
            "sign_method": "HMAC-SHA256",
            "t": timestamp,
            "nonce": nonce,
            "mode": "cors",
        }

        try:
            resp = self._http.get(
                f"{self._endpoint}{TOKEN_API_PREFIX}/token?grant_type=1",
                headers=headers,
            )
            data = resp.json()
        except httpx.TimeoutException as exc:
            raise TuyaNetworkError(f"Token request timed out: {exc}") from exc
        except httpx.NetworkError as exc:
            raise TuyaNetworkError(f"Token request network error: {exc}") from exc

        if not resp.is_success:
            self._handle_auth_error(resp, data)

        result = data.get("result", {})
        self._token = result.get("access_token", "")
        expire_seconds = result.get("expire_time", 7200)  # Tuya 默认 7200 秒
        self._token_expire_at = _now_ms() + expire_seconds * 1000

        if not self._token:
            raise TuyaAuthError("Access token is empty in response")

        # 缓存到文件
        _write_token_cache({
            "access_token": self._token,
            "expire_at": self._token_expire_at,
        })
        logger.info("Access token obtained and cached")
        return self._token

    # ── 设备发现（只读）────────────────────────────

    def list_devices(self) -> list[dict]:
        """列出账号下所有设备（用于发现红外遥控器）。"""
        # 用已知 device_id 查，Tuya 新 API 需要 device_ids 参数
        if self._infrared_id:
            path = f"{DEVICE_API_PREFIX}/devices/{self._infrared_id}"
            data = self._request_with_retry("GET", path)
            result = data.get("result", {}) if isinstance(data, dict) else {}
            return [result] if result else []
        # 回退：查设备列表（可能为空）
        path = f"{DEVICE_API_PREFIX}/devices"
        data = self._request_with_retry("GET", path)
        return data.get("result", []) if isinstance(data, dict) else []

    def list_remotes(self, infrared_id: str | None = None) -> list[dict]:
        """列出红外设备下的所有遥控器。

        Args:
            infrared_id: 红外设备 ID，不传则用配置中的值。
        """
        ir_id = infrared_id or self._infrared_id
        if not ir_id:
            raise TuyaAPIError("infrared_id is required to list remotes")

        path = f"{IR_API_PREFIX}/infrareds/{ir_id}/remotes"
        data = self._request_with_retry("GET", path)
        return data.get("result", []) if isinstance(data, dict) else []

    def list_learning_codes(
        self,
        infrared_id: str | None = None,
        remote_id: str | None = None,
    ) -> list[dict]:
        """列出遥控器下所有已学习的红外码。

        Args:
            infrared_id: 红外设备 ID，不传则用配置中的值。
            remote_id: 遥控器 ID，不传则用配置中的值。
        """
        ir_id = infrared_id or self._infrared_id
        rm_id = remote_id or self._remote_id
        if not ir_id:
            raise TuyaAPIError("infrared_id is required to list learning codes")
        if not rm_id:
            raise TuyaAPIError("remote_id is required to list learning codes")

        path = (
            f"{IR_API_PREFIX}/infrareds/{ir_id}"
            f"/remotes/{rm_id}/learning-codes"
        )
        data = self._request_with_retry("GET", path)
        return data.get("result", []) if isinstance(data, dict) else []

    def get_air_conditioner_status(
        self,
        remote_id: str,
        infrared_id: str | None = None,
    ) -> dict:
        """Read the last cloud-side state for a bound air-conditioner remote."""
        ir_id = infrared_id or self._infrared_id
        if not ir_id:
            raise TuyaAPIError("infrared_id is required to read AC status")
        if not remote_id:
            raise TuyaAPIError("remote_id is required to read AC status")

        path = (
            f"{IR_API_PREFIX}/infrareds/{ir_id}"
            f"/remotes/{remote_id}/ac/status"
        )
        data = self._request_with_retry("GET", path)
        result = data.get("result", {}) if isinstance(data, dict) else {}
        return result if isinstance(result, dict) else {}

    # ── 发送命令 ───────────────────────────────────

    def send_learning_code(
        self,
        code: str,
        infrared_id: str | None = None,
        remote_id: str | None = None,
    ) -> dict:
        """发送一条红外学习码。

        Args:
            code: 学习码字符串。
            infrared_id: 红外设备 ID。
            remote_id: 遥控器 ID。
        Returns:
            API 返回的 result 字典。
        """
        ir_id = infrared_id or self._infrared_id
        rm_id = remote_id or self._remote_id
        if not ir_id:
            raise TuyaAPIError("infrared_id is required to send command")
        if not rm_id:
            raise TuyaAPIError("remote_id is required to send command")
        if not code:
            raise TuyaAPIError("learning code is required to send command")

        path = (
            f"{IR_API_PREFIX}/infrareds/{ir_id}"
            f"/remotes/{rm_id}/learning-codes"
        )
        body = {"code": code}
        data = self._request_with_retry("POST", path, body=body)
        return data

    def send_air_conditioner_command(
        self,
        remote_id: str,
        code: str,
        value: int,
        infrared_id: str | None = None,
    ) -> dict:
        """Send one stateful command to a bound air-conditioner remote."""
        ir_id = infrared_id or self._infrared_id
        if not ir_id:
            raise TuyaAPIError("infrared_id is required to send AC command")
        if not remote_id:
            raise TuyaAPIError("remote_id is required to send AC command")
        if not code:
            raise TuyaAPIError("code is required to send AC command")

        path = (
            f"{IR_API_PREFIX}/infrareds/{ir_id}"
            f"/air-conditioners/{remote_id}/command"
        )
        body = {"code": code, "value": value}
        return self._request_with_retry("POST", path, body=body)

    # ── 内部方法 ───────────────────────────────────

    def _request_with_retry(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        _auth_retries_left: int = MAX_AUTH_RETRIES,
    ) -> dict:
        """发送 API 请求，带重试逻辑。"""
        network_retries = MAX_NETWORK_RETRIES

        while True:
            try:
                return self._do_request(method, path, body)
            except TuyaAuthError:
                # 认证错误：刷新 token 后重试（只重试有限次）
                if _auth_retries_left <= 0:
                    raise
                logger.warning(
                    "Auth error, refreshing token (%d retries left)",
                    _auth_retries_left,
                )
                self._token = None
                self._token_expire_at = 0
                # 删除缓存迫使重新获取
                try:
                    TOKEN_CACHE_FILE.unlink(missing_ok=True)
                except OSError:
                    pass
                _auth_retries_left -= 1
                continue
            except TuyaNetworkError:
                if network_retries <= 0:
                    raise
                network_retries -= 1
                wait = (MAX_NETWORK_RETRIES - network_retries) * 0.5
                logger.warning(
                    "Network error, retrying in %.1fs (%d retries left)",
                    wait,
                    network_retries,
                )
                time.sleep(wait)
                continue
            except TuyaAPIError:
                # 参数/业务错误，不重试
                raise

    def _do_request(self, method: str, path: str, body: dict | None = None) -> dict:
        """发送单次 API 请求（不重试）。"""
        token = self.get_access_token()
        timestamp = str(_now_ms())
        nonce = _gen_nonce()
        string_to_sign = _make_string_to_sign(method, path, body)
        sign = _build_sign(
            self._access_id, self._access_secret,
            timestamp, nonce, string_to_sign,
            access_token=token,
        )

        headers = {
            "client_id": self._access_id,
            "access_token": token,
            "sign": sign,
            "sign_method": "HMAC-SHA256",
            "t": timestamp,
            "nonce": nonce,
            "mode": "cors",
            "Content-Type": "application/json",
        }

        url = f"{self._endpoint}{path}"

        try:
            if method.upper() == "GET":
                resp = self._http.get(url, headers=headers)
            elif method.upper() == "POST":
                encoded_body = _serialize_body(body).encode("utf-8")
                resp = self._http.post(
                    url,
                    headers=headers,
                    content=encoded_body,
                )
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
        except httpx.TimeoutException as exc:
            raise TuyaNetworkError(f"Request timed out: {exc}") from exc
        except httpx.NetworkError as exc:
            raise TuyaNetworkError(f"Network error: {exc}") from exc

        try:
            data = resp.json()
        except json.JSONDecodeError:
            data = {"raw": resp.text}

        if resp.is_success and data.get("success", True) is not False:
            return data

        # 处理错误响应
        self._handle_error_response(resp, data)
        # _handle_error_response 应该总是 raise，但这里做兜底
        raise TuyaAPIError(f"Unexpected Tuya API response: {resp.status_code}")

    def _handle_error_response(self, resp: httpx.Response, data: dict) -> None:
        """根据 HTTP 状态码和响应体抛出对应异常。"""
        code = data.get("code", resp.status_code)
        msg = data.get("msg", "")

        # Tuya 常见错误码
        if code in (1004, 1010, 1011):  # token 相关
            raise TuyaAuthError(f"Tuya auth error [{code}]: {msg}")

        if code == 1012:  # 跨区
            raise TuyaRegionError(
                f"Tuya region mismatch [{code}]: {msg}. "
                f"Check TUYA_ENDPOINT and cloud project data center."
            )

        if resp.status_code >= 500:
            raise TuyaNetworkError(f"Tuya server error [{code}]: {msg}")

        # 其他 4xx → 参数/业务错误，不重试
        raise TuyaAPIError(f"Tuya API error [{code}]: {msg}")

    def _handle_auth_error(self, resp: httpx.Response, data: dict) -> None:
        """处理 token 请求的认证错误。"""
        code = data.get("code", resp.status_code)
        msg = data.get("msg", "")
        raise TuyaAuthError(
            f"Failed to obtain access token [{code}]: {msg}. "
            f"Check TUYA_ACCESS_ID and TUYA_ACCESS_SECRET."
        )

    def close(self) -> None:
        """关闭 HTTP 客户端。"""
        self._http.close()

    def __enter__(self) -> "TuyaClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
