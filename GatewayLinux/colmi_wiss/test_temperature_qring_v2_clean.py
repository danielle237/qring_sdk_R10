#!/usr/bin/env python3
import asyncio
import time
from datetime import datetime
from bleak import BleakClient

MAC = "30:32:42:32:64:01"
WRITE_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
NOTIFY_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"

# QRing SDK 1.0.0.7 - manualTemperature()
START_TEMP = bytes.fromhex("69 0B 25 00 00 00 00 00 00 00 00 00 00 00 00 99")
STOP_TEMP  = bytes.fromhex("6A 0B 00 00 00 00 00 00 00 00 00 00 00 00 00 75")

CAPTURE_SECONDS = 35

def stamp():
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]

def to_hex(data):
    return " ".join(f"{b:02X}" for b in bytes(data))

async def main():
    client = BleakClient(MAC)
    start_time = None
    rx_count = 0

    def notify(sender, data):
        nonlocal rx_count
        rx_count += 1
        raw = bytes(data)
        elapsed = time.perf_counter() - start_time if start_time else 0.0

        print(
            f"{stamp()} | RX #{rx_count:03d} | +{elapsed:7.3f}s | "
            f"{to_hex(raw)}",
            flush=True
        )

        # Do not trust this decoding yet: print it only as SDK candidate.
        if len(raw) >= 4 and raw[0] == 0x69 and raw[1] == 0x0B:
            err = raw[2]
            value = raw[3]
            temp = (value + 200) / 10.0
            print(
                f"{stamp()} | CANDIDATE 69 0B | "
                f"err={err} | raw={value} (0x{value:02X}) | "
                f"SDK candidate={temp:.1f}",
                flush=True
            )

    try:
        print("=" * 72)
        print("COLMI R10 - QRING TEMPERATURE RAW TEST V2 CLEAN")
        print(f"TARGET : {MAC}")
        print(f"START  : {to_hex(START_TEMP)}")
        print(f"STOP   : {to_hex(STOP_TEMP)}")
        print("=" * 72)

        print(f"{stamp()} | CONNECT START")
        await client.connect()
        print(f"{stamp()} | CONNECT OK")

        await client.start_notify(NOTIFY_UUID, notify)
        await asyncio.sleep(0.5)

        print(f"{stamp()} | TX START | {to_hex(START_TEMP)}")
        start_time = time.perf_counter()
        await client.write_gatt_char(WRITE_UUID, START_TEMP, response=False)

        await asyncio.sleep(CAPTURE_SECONDS)

        print(f"{stamp()} | TX STOP  | {to_hex(STOP_TEMP)}")
        await client.write_gatt_char(WRITE_UUID, STOP_TEMP, response=False)
        await asyncio.sleep(2)

        print(f"{stamp()} | RX TOTAL | {rx_count}")

    except Exception as e:
        print(f"{stamp()} | ERROR | {type(e).__name__}: {e}")

    finally:
        try:
            if client.is_connected:
                print(f"{stamp()} | DISCONNECT START")
                await client.disconnect()
                print(f"{stamp()} | DISCONNECT OK")
        except Exception as e:
            print(f"{stamp()} | DISCONNECT ERROR | {type(e).__name__}: {e}")

if __name__ == "__main__":
    asyncio.run(main())
