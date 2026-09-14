"""Route public resident MCP calls onto the Home Plugin Hub."""

from __future__ import annotations

from typing import Any

from plugin_hub.client import HubClient
from plugin_hub.residents import ResidentMcpRoute, ResidentRegistry


class HubMcpService:
    """One process-local Hub bridge shared by every configured App route."""

    def __init__(self, *, registry: ResidentRegistry, client: HubClient):
        self.registry = registry
        self.client = client

    def resolve_route(self, route_id: str) -> ResidentMcpRoute:
        return self.registry.resolve_mcp_route(route_id)

    def list_tools(self) -> list[dict[str, Any]]:
        """Return the Hub catalog verbatim: every tool, nothing filtered."""
        return [
            {
                "name": tool["function"]["name"],
                "description": tool["function"]["description"],
                "inputSchema": tool["function"]["parameters"],
            }
            for tool in self.client.list_tools()
        ]

    def call(
        self,
        route: ResidentMcpRoute,
        name: str,
        arguments: dict[str, Any],
    ) -> str:
        # The URL-selected route is trusted server context. The model may only
        # name a tool and pass its arguments; resident identity is injected
        # here and never accepted from the caller.
        host_context = {
            "client_id": route.resident_id,
            "memory_route": route.write_route.id,
        }
        return self.client.call_tool(name, arguments, host_context=host_context)
