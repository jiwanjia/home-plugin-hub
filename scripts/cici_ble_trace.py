"""Command-line wrapper for extracting Cici ATT writes from a local capture."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mcp_plugins.cici_ble_trace import load_capture, parse_att_writes


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract host-to-device ATT writes from btsnoop or bugreport zip."
    )
    parser.add_argument("capture", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    data = load_capture(args.capture)
    payload = [item.to_dict() for item in parse_att_writes(data)]
    encoded = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output is None:
        print(encoded)
    else:
        args.output.write_text(encoded + "\n", encoding="utf-8")
        print(f"wrote {len(payload)} ATT writes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
