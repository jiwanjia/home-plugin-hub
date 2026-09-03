"""Shared records used by the Home Plugin Hub catalog."""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from core.tool_base import ToolResult


ToolHandler = Callable[
    [Dict[str, Any], Optional[Dict[str, Any]]],
    ToolResult,
]


@dataclass
class ToolRecord:
    """One callable tool exported by a loaded plugin."""

    name: str
    description: str
    input_schema: Dict[str, Any]
    plugin_id: str
    handler: ToolHandler = field(repr=False)

    def to_openai_tool(self) -> Dict[str, Any]:
        """Return the existing Flask-compatible tool definition."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }

    def to_status(self) -> Dict[str, Any]:
        """Return the serializable portion used by doctor and future clients."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "plugin_id": self.plugin_id,
        }


@dataclass
class PluginRecord:
    """Runtime state for one manifest entry."""

    id: str
    kind: str
    enabled: bool
    status: str
    tools: List[ToolRecord] = field(default_factory=list)
    last_error: str = ""
    close_handler: Optional[Callable[[], None]] = field(
        default=None,
        repr=False,
    )
    release_scope_handler: Optional[Callable[[str], None]] = field(
        default=None,
        repr=False,
    )

    def to_status(self) -> Dict[str, Any]:
        """Return a serializable plugin status without executable handlers."""
        return {
            "id": self.id,
            "kind": self.kind,
            "enabled": self.enabled,
            "status": self.status,
            "tools": [tool.to_status() for tool in self.tools],
            "last_error": self.last_error,
        }
