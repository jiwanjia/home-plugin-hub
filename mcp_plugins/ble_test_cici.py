"""Retired guessed-packet writer retained as a migration notice."""


def main() -> int:
    print(
        "Blind BLE writes are disabled. Import a capture-verified profile "
        "and use the Home Hub cici_toy tool instead."
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
