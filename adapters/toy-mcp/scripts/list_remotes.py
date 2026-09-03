#!/usr/bin/env python3
"""列出红外设备下的所有 DIY 遥控器。

用途：找出遥控器 remote_id。

用法：
  cd /opt/toy-mcp
  python scripts/list_remotes.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import load_settings
from app.tuya_client import TuyaClient
from app.exceptions import ToyMCPError


def main() -> None:
    print("=" * 60)
    print("  Toy MCP — 列出遥控器")
    print("=" * 60)

    try:
        settings = load_settings()
    except ToyMCPError as exc:
        print(f"\n❌ 配置加载失败:\n  {exc}")
        sys.exit(1)

    infrared_id = settings.tuya_infrared_id
    if not infrared_id:
        print("\n❌ TUYA_INFRARED_ID 未设置。")
        print("   请先运行 discover_devices.py 找到红外设备 ID")
        print("   然后填入 .env 的 TUYA_INFRARED_ID")
        sys.exit(1)

    print(f"\n📍 Infrared ID: {infrared_id}")

    print("\n📡 正在查询遥控器列表...\n")
    try:
        with TuyaClient(settings) as client:
            remotes = client.list_remotes()
    except ToyMCPError as exc:
        print(f"❌ 请求失败: {exc}")
        sys.exit(1)

    if not remotes:
        print("⚠️  未找到任何遥控器。请检查:")
        print("   1. Infrared ID 是否正确")
        print("   2. 是否已在智能生活 App 中创建了 DIY 遥控器")
        print("   3. DIY 遥控器是否已学习至少一个按键")
        sys.exit(0)

    print(f"找到 {len(remotes)} 个遥控器:\n")
    for i, remote in enumerate(remotes, 1):
        name = remote.get("name", "(unknown)")
        rm_id = remote.get("id", remote.get("remote_id", "(unknown)"))
        category = remote.get("category_name", remote.get("category", "?"))

        print(f"  [{i}] {name}")
        print(f"      ID:       {rm_id}        ← 这就是 remote_id")
        print(f"      类别:     {category}")
        print()

    print("─" * 60)
    print("👉 把对应遥控器的 ID 填入 .env 的 TUYA_REMOTE_ID")
    print("=" * 60)


if __name__ == "__main__":
    main()
