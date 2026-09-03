"""Read-only GATT discovery helper for Cici on Windows."""

import asyncio

from bleak import BleakClient, BleakScanner


DEVICE_NAME = "Cici+ 2"


async def discover() -> None:
    device = await BleakScanner.find_device_by_name(DEVICE_NAME, timeout=8)
    if device is None:
        raise RuntimeError("Cici was not found nearby")
    print(f"=== connecting to {DEVICE_NAME} ===")
    async with BleakClient(device) as client:
        for service in client.services:
            print(f"service {service.uuid}: {service.description}")
            for characteristic in service.characteristics:
                properties = ",".join(characteristic.properties)
                print(
                    f"  characteristic {characteristic.uuid} "
                    f"handle={characteristic.handle} properties={properties}"
                )


if __name__ == "__main__":
    asyncio.run(discover())
