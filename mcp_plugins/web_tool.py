"""MCP plugin for fetching web content with the Python standard library."""

import logging
import re
import ssl
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from core.tool_base import MCPlugin, ToolResult

logger = logging.getLogger(__name__)

# 模拟正常浏览器
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def _strip_html(html: str) -> str:
    """简单去除 HTML 标签"""
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()[:3000]


def _read_response(url: str, ssl_context=None) -> tuple[int, str, str]:
    request = Request(url, headers=HEADERS)
    with urlopen(request, timeout=15, context=ssl_context) as response:
        content_type = response.headers.get("Content-Type", "")
        charset = response.headers.get_content_charset() or "utf-8"
        text = response.read().decode(charset, errors="replace")
        return response.status, content_type, text


class WebFetchPlugin(MCPlugin):
    @property
    def name(self) -> str:
        return "web_fetch"

    @property
    def description(self) -> str:
        return "获取网页内容（支持 HTTPS / 重定向 / 反爬基础处理）"

    @property
    def parameters(self) -> dict:
        return {
            "url": {
                "type": "string",
                "description": "要获取的网页 URL",
            }
        }

    def execute(self, url: str = "") -> ToolResult:
        logger.info(f"获取网页: {url[:100]}")
        if not url:
            return ToolResult.fail("请提供 URL", operation="read")

        # 自动补 https
        if not url.startswith("http"):
            url = "https://" + url

        try:
            status, content_type, response_text = _read_response(url)

            if "json" in content_type:
                data = (
                    f"📦 JSON ({len(response_text)} 字符)\n\n"
                    f"{response_text[:3000]}"
                )
            else:
                text = _strip_html(response_text)
                data = f"🌐 {url}\n\n{text[:3000]}"

            return ToolResult.success(
                data=data,
                operation="read",
                path=url,
                hints=[f"HTTP {status}, Content-Type: {content_type}"]
            )

        except URLError as error:
            if not isinstance(error.reason, ssl.SSLError):
                return ToolResult.fail(
                    f"获取失败: {error}", operation="read", path=url
                )
            try:
                status, content_type, response_text = _read_response(
                    url,
                    ssl._create_unverified_context(),
                )
                text = _strip_html(response_text)
                return ToolResult.success(
                    data=f"🌐 {url} (SSL 警告已忽略)\n\n{text[:3000]}",
                    operation="read",
                    path=url,
                    hints=[
                        "⚠️ SSL 证书验证已跳过",
                        f"HTTP {status}, Content-Type: {content_type}",
                    ],
                )
            except Exception as retry_error:
                return ToolResult.fail(
                    f"获取失败 (SSL): {retry_error}",
                    operation="read",
                    path=url,
                )

        except HTTPError as error:
            return ToolResult.fail(
                f"HTTP 错误 {error.code}: {url}",
                operation="read",
                path=url,
            )

        except TimeoutError:
            return ToolResult.fail(f"获取超时: {url}", operation="read", path=url)

        except Exception as error:
            return ToolResult.fail(
                f"获取失败: {error}", operation="read", path=url
            )
