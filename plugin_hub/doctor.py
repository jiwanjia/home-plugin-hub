"""Read-only command line view of the running Home Plugin Hub."""

from typing import Dict

from .client import HubClient, HubClientError


def format_status(status: Dict) -> str:
    """Format the same status payload future Web clients will consume."""
    lines = [
        "Home Plugin Hub",
        "",
        "[ONLINE] Hub",
        f"Manifest: {status['manifest']}",
        f"Pipe: {status.get('pipe_name', 'unknown')}",
    ]

    groups = [
        ("Local Python Plugins", "python"),
        ("Continuum Services", "continuum"),
        ("External MCP", "mcp_stdio"),
    ]
    for label, kind in groups:
        plugins = [
            plugin
            for plugin in status["plugins"]
            if plugin["kind"] == kind
        ]
        lines.extend(["", label])
        if not plugins:
            lines.append("[NONE]")
            continue
        for plugin in plugins:
            lines.append(_plugin_summary(plugin))

    lines.extend(
        [
            "",
            "Total",
            f"Plugins: {status['plugin_count']}",
            f"Tools: {status['tool_count']}",
            f"Failed: {status['failed_count']}",
        ]
    )
    return "\n".join(lines)


def _plugin_summary(plugin: Dict) -> str:
    marker = _status_marker(plugin["status"])
    tool_names = ", ".join(
        tool["name"]
        for tool in plugin["tools"]
    )
    tool_count = len(plugin["tools"])
    summary = f"{marker} {plugin['id']:<20} {tool_count} tool"
    if tool_count != 1:
        summary += "s"
    if tool_names:
        summary += f"  {tool_names}"
    if plugin["last_error"]:
        summary += f"  error={plugin['last_error']}"
    return summary


def _status_marker(status: str) -> str:
    markers = {
        "OK": "[OK]",
        "DISABLED": "[OFF]",
        "FAILED": "[FAIL]",
    }
    return markers.get(status, f"[{status}]")


def main() -> int:
    """Print status from the sole running Catalog."""
    client = HubClient.from_manifest()
    try:
        status = client.status()
    except HubClientError as exc:
        print("Home Plugin Hub")
        print("")
        print(f"[OFFLINE] {exc}")
        return 1

    print(format_status(status))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
