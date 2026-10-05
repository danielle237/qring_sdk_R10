#!/usr/bin/env python3
"""
EIS / COLMI R10 - HRV QRing exact diagnostic V1

Derived from QRing Android SDK 1.0.0.7:
- manualModeHrv() -> StartHeartRateReq.getSimpleReq(0x0A)
- SDK timeout: 80 s
- response value: HRV = packet byte 3 for 69 0A ...
- when HRV > 0, QRing sends STOP with the measured HRV value.

No unit is assumed here.
"""

import asyncio
import time
from datetime import datetime
from bleak import BleakClient

MAC = "30:32:42:32:64:01"
WRITE_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
NOTIFY_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"

START_HRV = bytes.fromhex(
    "69 0A 25 00 00 00 00 00 00 00 00 00 00 00 00 98"
)

TIMEOUT = 80.0


def stamp():
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def hx(data):
    return " ".join(f"{b:02X}" for b in bytes(data))


def make_stop_hrv(value):
    # QRing: StopHeartRateReq.stopHrv((byte)hrv)
    packet = bytearray(16)
    packet[0] = 0x6A
    packet[1] = 0x0A
    packet[2] = value & 0xFF
    packet[3] = 0x00
    packet[15] = sum(packet[:15]) & 0xFF
    return bytes(packet)


async def main():
    client = BleakClient(MAC)
    done = asyncio.Event()
    t0 = None
    result = {"hrv": None, "rri": None, "packet": None, "elapsed": None}

    def notify(_sender, data):
        raw = bytes(data)

        if len(raw) < 4:
            return
        if raw[0] != 0x69 or raw[1] != 0x0A:
            return

        elapsed = time.perf_counter() - t0 if t0 else 0.0
        err = raw[2]
        value = raw[3]

        # StopHeartRateRsp parser in QRing also reads RRI from payload[5:7],
        # i.e. full packet bytes 6:8. Print it only for diagnosis.
        rri = None
        if len(raw) >= 8:
            rri = int.from_bytes(raw[6:8], byteorder="big", signed=False)

        print(
            f"{stamp()} | RX | +{elapsed:7.3f}s | "
            f"err={err} | HRV={value} | RRI={rri} | HEX={hx(raw)}",
            flush=True,
        )

        if err != 0:
            result["packet"] = raw
            result["elapsed"] = elapsed
            done.set()
            return

        if value > 0 and result["hrv"] is None:
            result["hrv"] = value
            result["rri"] = rri
            result["packet"] = raw
            result["elapsed"] = elapsed
            done.set()

    print("=" * 72)
    print("EIS / COLMI R10 - HRV QRING EXACT DIAGNOSTIC V1")
    print(f"TARGET  : {MAC}")
    print(f"START   : {hx(START_HRV)}")
    print(f"TIMEOUT : {TIMEOUT:.0f}s (same limit as QRing SDK)")
    print("UNIT    : intentionally not assumed")
    print("=" * 72)

    try:
        c0 = time.perf_counter()
        print(f"{stamp()} | CONNECT START")
        await client.connect()
        print(f"{stamp()} | CONNECT OK | {time.perf_counter()-c0:.3f}s")

        await client.start_notify(NOTIFY_UUID, notify)
        await asyncio.sleep(0.5)

        print(f"{stamp()} | HRV START | {hx(START_HRV)}")
        t0 = time.perf_counter()
        await client.write_gatt_char(WRITE_UUID, START_HRV, response=False)

        try:
            await asyncio.wait_for(done.wait(), timeout=TIMEOUT)
        except asyncio.TimeoutError:
            print(f"{stamp()} | HRV TIMEOUT | no positive HRV value")

        if result["hrv"] is not None:
            stop = make_stop_hrv(result["hrv"])
            print(
                f"{stamp()} | FIRST VALID | +{result['elapsed']:.3f}s | "
                f"HRV={result['hrv']} | RRI={result['rri']}"
            )
            print(f"{stamp()} | HRV STOP | {hx(stop)}")
            await client.write_gatt_char(WRITE_UUID, stop, response=False)
            await asyncio.sleep(0.5)

            print("")
            print("=" * 72)
            print("RESULT")
            print(f"HRV         : {result['hrv']}")
            print(f"RRI         : {result['rri']}  (diagnostic only)")
            print(f"First valid : {result['elapsed']:.3f}s")
            print(f"HEX         : {hx(result['packet'])}")
            print("=" * 72)
        else:
            # SDK manual stop path uses stopHrv(0)
            stop = make_stop_hrv(0)
            print(f"{stamp()} | HRV STOP(0) | {hx(stop)}")
            await client.write_gatt_char(WRITE_UUID, stop, response=False)
            await asyncio.sleep(0.5)

    except Exception as e:
        print(f"{stamp()} | ERROR | {type(e).__name__}: {e}")

    finally:
        try:
            if client.is_connected:
                print(f"{stamp()} | DISCONNECT START")
                await client.disconnect()
                print(f"{stamp()} | DISCONNECT OK")
        except Exception as e:
            print(f"{stamp()} | DISCONNECT WARNING | {type(e).__name__}: {e}")


if __name__ == "__main__":
    asyncio.run(main())
