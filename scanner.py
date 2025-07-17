import asyncio
from bleak import BleakScanner

async def scan_beacons(timeout=5):
    print(f"🔍 Đang quét beacon BLE trong {timeout} giây...\n")
    devices = await BleakScanner.discover(timeout=timeout)

    if not devices:
        print("⚠️ Không tìm thấy thiết bị BLE nào.")
        return

    print(f"✅ Tìm thấy {len(devices)} thiết bị:")
    print("="*60)
    for idx, d in enumerate(devices, 1):
        print(f"{idx:02}. 📡 MAC: {d.address}")
        print(f"    📛 Name: {d.name or 'Không xác định'}")
        print(f"    📶 RSSI: {d.rssi} dBm")
        print("-"*60)

if __name__ == "__main__":
    asyncio.run(scan_beacons(timeout=5))
