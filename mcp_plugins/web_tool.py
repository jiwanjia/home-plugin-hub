"""
MCP 插件: Web 获取工具（抓取网页内容）
使用 requests 库，支持 HTTPS / 重定向 / 现代 Web
"""
import logging
import re
import requests
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
            resp = requests.get(
                url, headers=HEADERS, timeout=15,
                allow_redirects=True, verify=True
            )
            resp.raise_for_status()
            content_type = resp.headers.get("Content-Type", "")

            if "json" in content_type:
                text = resp.text
                data = f"📦 JSON ({len(text)} 字符)\n\n{text[:3000]}"
            else:
                resp.encoding = resp.apparent_encoding or "utf-8"
                html = resp.text
                text = _strip_html(html)
                data = f"🌐 {url}\n\n{text[:3000]}"

            return ToolResult.success(
                data=data,
                operation="read",
                path=url,
                hints=[f"HTTP {resp.status_code}, Content-Type: {content_type}"]
            )

        except requests.exceptions.SSLError:
            try:
                resp = requests.get(
                    url, headers=HEADERS, timeout=15,
                    allow_redirects=True, verify=False
                )
                resp.encoding = resp.apparent_encoding or "utf-8"
                text = _strip_html(resp.text)
                return ToolResult.success(
                    data=f"🌐 {url} (SSL 警告已忽略)\n\n{text[:3000]}",
                    operation="read",
                    path=url,
                    hints=["⚠️ SSL 证书验证已跳过"]
                )
            except Exception as e:
                return ToolResult.fail(f"获取失败 (SSL): {e}", operation="read", path=url)

        except requests.exceptions.Timeout:
            return ToolResult.fail(f"获取超时: {url}", operation="read", path=url)

        except requests.exceptions.HTTPError as e:
            return ToolResult.fail(
                f"HTTP 错误 {e.response.status_code}: {url}",
                operation="read", path=url
            )

        except Exception as e:
            return ToolResult.fail(f"获取失败: {e}", operation="read", path=url)
