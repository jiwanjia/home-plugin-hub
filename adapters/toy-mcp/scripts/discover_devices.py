#!/usr/bin/env python3
"""发现 Tuya 账号下的所有设备。

用途：找出红外遥控器的 infrared_id。

输出：
  - 设备名称、设备 ID、是否在线
  - 不输出 Access Secret、token

用法：
  cd /opt/toy-mcp
  python scripts/discover_devices.py
"""

from __future__ import annotations

import os
import sys

# 把项目根加入 sys.path，方便直接运行脚本
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import load_settings, Settings
from app.tuya_client import TuyaClient
from app.exceptions import ToyMCPError


def main() -> None:
    print("=" * 60)
    print("  Toy MCP — 发现设备")
    print("=" * 60)

    # 加载配置
    try:
        settings = load_settings()
    except ToyMCPError as exc:
        print(f"\n❌ 配置加载失败:\n  {exc}")
        sys.exit(1)

    print(f"\n📍 Endpoint: {settings.tuya_endpoint}")
    print(f"🔑 Access ID: {settings.tuya_access_id[:4]}***")

    # 查询设备
    print("\n📡 正在查询设备列表...\n")
    try:
        with TuyaClient(settings) as client:
            devices = client.list_devices()
    except ToyMCPError as exc:
        print(f"❌ 请求失败: {exc}")
        sys.exit(1)

    if not devices:
        print("⚠️  未找到任何设备。请检查:")
        print("   1. Tuya 云项目是否已关联智能生活 App 账号")
        print("   2. 红外遥控器是否已完成 App 配网")
        print("   3. Access ID / Secret 是否正确")
        sys.exit(0)

    # 打印结果
    print(f"找到 {len(devices)} 个设备:\n")
    for i, dev in enumerate(devices, 1):
        name = dev.get("name", "(unknown)")
        dev_id = dev.get("id", "(unknown)")
        online = dev.get("online", False)
        status = "🟢 在线" if online else "🔴 离线"
        category = dev.get("category_name", dev.get("category", "?"))

        print(f"  [{i}] {name}")
        print(f"      ID:       {dev_id}        ← 这就是 infrared_id")
        print(f"      类别:     {category}")
        print(f"      状态:     {status}")
        print()

    print("─" * 60)
    print("👉 把红外遥控器对应的 ID 填入 .env 的 TUYA_INFRARED_ID")
    print("=" * 60)


if __name__ == "__main__":
    main()
