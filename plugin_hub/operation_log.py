"""In-memory operation history owned by the single Hub process."""

from typing import Dict, List

from core.tool_base import ToolResult


class HubOperationLog:
    """Keep the recent structured tool results for status clients."""

    def __init__(self, maximum_entries: int = 200):
        self._maximum_entries = maximum_entries
        self._entries: List[Dict] = []

    def record(self, tool_name: str, result: ToolResult) -> None:
        entry = result.to_dict()
        entry["tool"] = tool_name
        self._entries.append(entry)
        if len(self._entries) > self._maximum_entries:
            self._entries = self._entries[-self._maximum_entries:]

    def recent(self, limit: int = 20) -> List[Dict]:
        safe_limit = max(0, min(limit, self._maximum_entries))
        if safe_limit == 0:
            return []
        return list(self._entries[-safe_limit:])

    def summary(self) -> str:
        if not self._entries:
            return "（本次 Hub 运行尚未调用任何工具）"

        read_count = sum(
            1 for entry in self._entries
            if entry["operation"] == "read"
        )
        write_count = sum(
            1 for entry in self._entries
            if entry["operation"] == "write"
        )
        failed_count = sum(
            1 for entry in self._entries
            if not entry["ok"]
        )
        return (
            f"本次 Hub 运行共 {len(self._entries)} 次调用"
            f" | {read_count} 读 {write_count} 写"
            f" | {failed_count} 失败"
        )
