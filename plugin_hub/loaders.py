"""Load existing MCPlugin classes into neutral Hub tool records."""

from __future__ import annotations

import importlib
from typing import Any, Callable, Dict, List, Optional, Type

from core.tool_base import MCPlugin, ToolResult

from .contracts import ToolRecord
from .manifest import PluginConfig
from .mcp_stdio_client import McpStdioClient, McpStdioError


class PluginLoadError(RuntimeError):
    """Raised when one manifest entry cannot become a callable plugin."""


def load_python_plugin(
    config: PluginConfig,
) -> tuple[
    ToolRecord,
    Callable[[], None],
    Callable[[str], None],
]:
    """Instantiate one MCPlugin and expose its host lifecycle callback."""
    plugin_class = _import_plugin_class(config.entrypoint)

    try:
        plugin = plugin_class()
    except Exception as exc:
        raise PluginLoadError(
            f"插件 {config.id} 实例化失败: {exc}"
        ) from exc

    if not isinstance(plugin, MCPlugin):
        raise PluginLoadError(
            f"插件 {config.id} 的类必须继承 MCPlugin"
        )

    openai_tool = plugin.to_openai_tool()
    function_spec = openai_tool["function"]

    def handler(
        arguments: Dict[str, Any],
        host_context: Optional[Dict[str, Any]] = None,
    ) -> ToolResult:
        try:
            result = plugin.execute_with_context(arguments, host_context)
        except Exception as exc:
            result = ToolResult.fail(
                str(exc),
                operation=plugin.name,
            )

        if not isinstance(result, ToolResult):
            raise PluginLoadError(
                f"工具 {plugin.name} 必须返回 ToolResult"
            )
        return result

    tool = ToolRecord(
        name=function_spec["name"],
        description=function_spec["description"],
        input_schema=function_spec["parameters"],
        plugin_id=config.id,
        handler=handler,
    )
    return tool, plugin.close, plugin.release_execution_scope


def load_continuum_provider(config: PluginConfig) -> List[ToolRecord]:
    """Load the read-only Continuum provider without opening memory stores."""
    provider_class = _import_entrypoint_class(config.entrypoint)
    try:
        provider = provider_class()
        tools = provider.get_tools(config.id)
    except Exception as exc:
        raise PluginLoadError(
            f"Continuum provider {config.id} 加载失败: {exc}"
        ) from exc

    if not isinstance(tools, list) or not tools:
        raise PluginLoadError(
            f"Continuum provider {config.id} 必须提供至少一个工具"
        )
    if not all(isinstance(tool, ToolRecord) for tool in tools):
        raise PluginLoadError(
            f"Continuum provider {config.id} 返回了无效工具"
        )
    return tools


def load_mcp_stdio_plugin(
    config: PluginConfig,
) -> tuple[List[ToolRecord], McpStdioClient]:
    """Start one external MCP process and adapt all of its tools."""
    client = McpStdioClient(
        config.command,
        config.args,
        config.env_vars,
    )
    try:
        tool_specs = client.list_tools()
        tools = [
            _mcp_tool_record(config.id, client, tool_spec)
            for tool_spec in tool_specs
        ]
    except Exception:
        client.close()
        raise
    if not tools:
        client.close()
        raise PluginLoadError(
            f"外部 MCP {config.id} 没有提供工具"
        )
    return tools, client


def _mcp_tool_record(
    plugin_id: str,
    client: McpStdioClient,
    tool_spec: Dict[str, Any],
) -> ToolRecord:
    name = tool_spec.get("name")
    description = tool_spec.get("description", "")
    input_schema = tool_spec.get("inputSchema", {"type": "object"})
    if not isinstance(name, str) or not name:
        raise PluginLoadError(f"外部 MCP {plugin_id} 的工具缺少名称")
    if not isinstance(description, str):
        raise PluginLoadError(f"外部 MCP 工具 {name} 的描述无效")
    if not isinstance(input_schema, dict):
        raise PluginLoadError(f"外部 MCP 工具 {name} 的 Schema 无效")

    def handler(
        arguments: Dict[str, Any],
        host_context: Optional[Dict[str, Any]] = None,
    ) -> ToolResult:
        del host_context
        try:
            result = client.call_tool(name, arguments)
        except McpStdioError as exc:
            return ToolResult.fail(
                str(exc),
                operation=name,
            )
        content = result.get("content", [])
        text_parts = [
            item.get("text", "")
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        text = "\n".join(part for part in text_parts if part)
        if result.get("isError") is True:
            return ToolResult.fail(text or "外部 MCP 调用失败", operation=name)
        return ToolResult.success(text, operation=name)

    return ToolRecord(
        name=name,
        description=description,
        input_schema=input_schema,
        plugin_id=plugin_id,
        handler=handler,
    )


def _import_plugin_class(entrypoint: str) -> Type[MCPlugin]:
    plugin_class = _import_entrypoint_class(entrypoint)
    return plugin_class


def _import_entrypoint_class(entrypoint: str):
    module_name, separator, class_name = entrypoint.partition(":")
    if not separator or not module_name or not class_name:
        raise PluginLoadError(
            f"无效 entrypoint: {entrypoint!r}，应为 module:Class"
        )

    try:
        module = importlib.import_module(module_name)
    except Exception as exc:
        raise PluginLoadError(
            f"无法导入模块 {module_name}: {exc}"
        ) from exc

    try:
        plugin_class = getattr(module, class_name)
    except AttributeError as exc:
        raise PluginLoadError(
            f"模块 {module_name} 中不存在 {class_name}"
        ) from exc

    if not isinstance(plugin_class, type):
        raise PluginLoadError(f"{entrypoint} 不是类")
    return plugin_class
