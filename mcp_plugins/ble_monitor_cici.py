"""Retired second-central monitor retained as a migration notice."""


def main() -> int:
    print(
        "A second Bleak client cannot observe writes sent by the SVA app. "
        "Use scripts/cici_ble_trace.py with an Android HCI snoop capture."
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
