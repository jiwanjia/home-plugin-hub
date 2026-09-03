#!/usr/bin/env python3
"""列出遥控器下所有已学习的红外码。

用途：找出电源、拍打、减速、加速对应的 learning code。

输出会完整显示 code 值，供用户复制到 .env。

用法：
  cd /opt/toy-mcp
  python scripts/list_learning_codes.py
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
    print("  Toy MCP — 列出学习码")
    print("=" * 60)

    try:
        settings = load_settings()
    except ToyMCPError as exc:
        print(f"\n❌ 配置加载失败:\n  {exc}")
        sys.exit(1)

    infrared_id = settings.tuya_infrared_id
    remote_id = settings.tuya_remote_id

    if not infrared_id:
        print("\n❌ TUYA_INFRARED_ID 未设置。")
        sys.exit(1)
    if not remote_id:
        print("\n❌ TUYA_REMOTE_ID 未设置。")
        print("   请先运行 list_remotes.py 找到遥控器 ID")
        sys.exit(1)

    print(f"\n📍 Infrared ID: {infrared_id}")
    print(f"📍 Remote ID:    {remote_id}")

    print("\n📡 正在查询学习码列表...\n")
    try:
        with TuyaClient(settings) as client:
            codes = client.list_learning_codes()
    except ToyMCPError as exc:
        print(f"❌ 请求失败: {exc}")
        sys.exit(1)

    if not codes:
        print("⚠️  未找到任何学习码。请检查:")
        print("   1. 遥控器 ID 是否正确")
        print("   2. 是否已在智能生活 App 的 DIY 遥控器中学习按键")
        sys.exit(0)

    print(f"找到 {len(codes)} 个学习码:\n")
    for i, item in enumerate(codes, 1):
        name = item.get("name", item.get("key_name", f"按键 {i}"))
        code = item.get("code", item.get("learning_code", ""))
        print(f"  [{i}] 名称: {name}")
        print(f"      码值: {code}")
        print()

    print("─" * 60)
    print("👉 确认每个按键的名称与码值，填入 .env：")
    print("   TOY_POWER_CODE=<电源键的码值>")
    print("   TOY_PAT_CODE=<拍打键的码值>")
    print("   TOY_SLOW_CODE=<减速键的码值>")
    print("   TOY_FAST_CODE=<加速键的码值>")
    print("=" * 60)


if __name__ == "__main__":
    main()
