"""Authoritative in-process catalog for the Home Plugin Hub."""

from pathlib import Path
from typing import Any, Dict, List, Optional

from core.tool_base import ToolResult

from .contracts import PluginRecord, ToolRecord
from .loaders import (
    load_continuum_provider,
    load_mcp_stdio_plugin,
    load_python_plugin,
)
from .manifest import HubManifest, PluginConfig, load_manifest
from .operation_log import HubOperationLog


class HubError(RuntimeError):
    """Base error returned by the Hub core."""


class ToolNotFoundError(HubError):
    """Raised when a caller requests a tool outside the active catalog."""


class DuplicateToolError(HubError):
    """Raised when two plugins attempt to export the same public name."""


class UnsupportedPluginKindError(HubError):
    """Raised until a later slice implements the configured plugin kind."""


class PluginHub:
    """Load one manifest into one authoritative plugin and tool catalog."""

    def __init__(self, manifest_path: Path):
        self._manifest_path = Path(manifest_path)
        self._manifest: Optional[HubManifest] = None
        self._plugins: Dict[str, PluginRecord] = {}
        self._tools: Dict[str, ToolRecord] = {}
        self._operation_log = HubOperationLog()
        self._started = False

    def start(self) -> None:
        """Load all entries with per-plugin failure isolation."""
        if self._started:
            return

        self._manifest = load_manifest(self._manifest_path)
        for config in self._manifest.plugins:
            self._load_plugin(config)
        self._started = True

    def list_plugins(self) -> List[Dict[str, Any]]:
        """Return every configured plugin, including disabled and failed ones."""
        self._ensure_started()
        return [
            plugin.to_status()
            for plugin in self._plugins.values()
        ]

    def list_tools(self) -> List[Dict[str, Any]]:
        """Return the active tools in the existing OpenAI-compatible format."""
        self._ensure_started()
        return [
            tool.to_openai_tool()
            for tool in self._tools.values()
        ]

    def call_tool(
        self,
        name: str,
        arguments: Dict[str, Any],
        host_context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Call one active tool while keeping host identity out of model args."""
        return self.call_tool_result(
            name,
            arguments,
            host_context,
        ).to_message()

    def call_tool_result(
        self,
        name: str,
        arguments: Dict[str, Any],
        host_context: Optional[Dict[str, Any]] = None,
    ) -> ToolResult:
        """Call one tool and preserve its structured success state."""
        self._ensure_started()
        tool = self._tools.get(name)
        if tool is None:
            raise ToolNotFoundError(f"未知或不可用工具: {name}")
        if not isinstance(arguments, dict):
            raise HubError("工具参数必须是对象")
        result = tool.handler(arguments, host_context)
        if not isinstance(result, ToolResult):
            raise HubError(f"工具 {name} 返回了无效结果")
        self._operation_log.record(name, result)
        return result

    def get_operation_log(self, limit: int = 20) -> List[Dict[str, Any]]:
        self._ensure_started()
        return self._operation_log.recent(limit)

    def get_operation_summary(self) -> str:
        self._ensure_started()
        return self._operation_log.summary()

    def status(self) -> Dict[str, Any]:
        """Return the serializable source of truth used by future clients."""
        self._ensure_started()
        failed = sum(
            1
            for plugin in self._plugins.values()
            if plugin.status == "FAILED"
        )
        return {
            "online": True,
            "manifest": str(self._manifest_path),
            "plugin_count": len(self._plugins),
            "tool_count": len(self._tools),
            "failed_count": failed,
            "plugins": self.list_plugins(),
        }

    def close(self) -> None:
        """Release loaded handlers and external MCP child processes."""
        for plugin in self._plugins.values():
            if plugin.close_handler is not None:
                plugin.close_handler()
        self._tools.clear()
        self._plugins.clear()
        self._manifest = None
        self._started = False

    def release_execution_scope(self, scope_id: str) -> None:
        """Release resources owned by one hidden host reply scope."""
        self._ensure_started()
        if not isinstance(scope_id, str) or not scope_id:
            raise HubError("execution scope 必须是非空字符串")
        for plugin in self._plugins.values():
            if plugin.release_scope_handler is not None:
                plugin.release_scope_handler(scope_id)

    def _load_plugin(self, config: PluginConfig) -> None:
        record = PluginRecord(
            id=config.id,
            kind=config.kind,
            enabled=config.enabled,
            status="DISABLED" if not config.enabled else "LOADING",
        )
        self._plugins[config.id] = record
        if not config.enabled:
            return

        try:
            tools = self._load_tools(config, record)
            self._register_tools(record, tools)
        except Exception as exc:
            record.status = "FAILED"
            record.last_error = str(exc)
            record.tools.clear()

    def _load_tools(
        self,
        config: PluginConfig,
        record: PluginRecord,
    ) -> List[ToolRecord]:
        if config.kind == "python":
            loaded_plugin = load_python_plugin(config)
            tool, close_handler, release_scope_handler = loaded_plugin
            record.close_handler = close_handler
            record.release_scope_handler = release_scope_handler
            return [tool]
        if config.kind == "continuum":
            return load_continuum_provider(config)
        if config.kind == "mcp_stdio":
            tools, client = load_mcp_stdio_plugin(config)
            record.close_handler = client.close
            return tools
        raise UnsupportedPluginKindError(
            f"插件 {config.id} 的 kind {config.kind} 尚未在本切片启用"
        )

    def _register_tools(
        self,
        plugin: PluginRecord,
        tools: List[ToolRecord],
    ) -> None:
        pending_names = set()
        for tool in tools:
            if tool.name in pending_names:
                raise DuplicateToolError(
                    f"插件 {plugin.id} 内部工具名重复: {tool.name}"
                )
            if tool.name in self._tools:
                existing = self._tools[tool.name]
                raise DuplicateToolError(
                    f"工具名冲突: {tool.name} 已由 {existing.plugin_id} 提供"
                )
            pending_names.add(tool.name)

        for tool in tools:
            self._tools[tool.name] = tool
            plugin.tools.append(tool)
        plugin.status = "OK"

    def _ensure_started(self) -> None:
        if not self._started:
            raise HubError("Plugin Hub 尚未启动")
