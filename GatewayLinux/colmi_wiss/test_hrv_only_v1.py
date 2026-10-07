#!/usr/bin/env python3
import asyncio
import statistics
import time
from datetime import datetime
from bleak import BleakClient

MAC = "30:32:42:32:64:01"
WRITE_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
NOTIFY_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

TARGET_SAMPLES = 6
TIMEOUT = 45.0

def make_packet(cmd, payload):
    p = bytearray(16)
    p[0] = cmd
    p[1:1 + len(payload)] = bytes(payload)
    p[15] = sum(p[:15]) & 0xFF
    return bytes(p)

# Exact colmi_r02_client V1 method:
# 0x69 = START_REAL_TIME, 0x0A = HRV, 0x01 = START
START_HRV = make_packet(0x69, [0x0A, 0x01])
STOP_HRV = make_packet(0x6A, [0x0A, 0x00, 0x00])

def stamp():
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]

def hexdump(data):
    return " ".join(f"{b:02X}" for b in data)

async def main():
    samples = []
    first_valid = None
    error_code = None
    done = asyncio.Event()
    t_start = None

    def callback(sender, data):
        nonlocal first_valid, error_code
        packet = bytes(data)

        if len(packet) < 4:
            return
        if packet[0] != 0x69 or packet[1] != 0x0A:
            return

        elapsed = time.perf_counter() - t_start if t_start else 0.0
        err = packet[2]
        value = packet[3]

        if err != 0:
            error_code = err
            print(f"{stamp()} | HRV ERROR | code={err} | HEX={hexdump(packet)}", flush=True)
            done.set()
            return

        if value == 0:
            return

        if first_valid is None:
            first_valid = elapsed
            print(f"{stamp()} | FIRST VALID | +{elapsed:.3f}s | HRV={value}", flush=True)

        if len(samples) < TARGET_SAMPLES:
            samples.append(value)
            print(f"{stamp()} | SAMPLE {len(samples)}/{TARGET_SAMPLES} | HRV={value}", flush=True)

        if len(samples) >= TARGET_SAMPLES:
            done.set()

    print("=" * 70)
    print("EIS / COLMI R10 - HRV ONLY - V1 PROTOCOL")
    print(f"TARGET : {MAC}")
    print(f"START  : {hexdump(START_HRV)}")
    print(f"STOP   : {hexdump(STOP_HRV)}")
    print("UNIT   : unknown - no unit assumed")
    print("=" * 70)

    client = BleakClient(MAC)

    try:
        c0 = time.perf_counter()
        print(f"{stamp()} | CONNECT START")
        await client.connect()
        print(f"{stamp()} | CONNECT OK | {time.perf_counter() - c0:.3f}s")

        await client.start_notify(NOTIFY_UUID, callback)
        await asyncio.sleep(0.5)

        t_start = time.perf_counter()
        print(f"{stamp()} | HRV START")
        await client.write_gatt_char(WRITE_UUID, START_HRV, response=False)

        try:
            await asyncio.wait_for(done.wait(), timeout=TIMEOUT)
        except asyncio.TimeoutError:
            print(f"{stamp()} | HRV TIMEOUT | {len(samples)}/{TARGET_SAMPLES} samples")

        measure_time = time.perf_counter() - t_start

        print(f"{stamp()} | HRV STOP")
        await client.write_gatt_char(WRITE_UUID, STOP_HRV, response=False)
        await asyncio.sleep(0.5)

        print()
        print("=== RESULT ===")
        print(f"Samples      : {samples}")
        if samples:
            print(f"Median       : {statistics.median(samples)}")
        if first_valid is not None:
            print(f"First valid  : {first_valid:.3f}s")
        if error_code is not None:
            print(f"Error code   : {error_code}")
        print(f"Measure time : {measure_time:.3f}s")

    except Exception as e:
        print(f"{stamp()} | ERROR | {type(e).__name__}: {e}")

    finally:
        if client.is_connected:
            try:
                await client.disconnect()
                print(f"{stamp()} | DISCONNECT OK")
            except Exception as e:
                print(f"{stamp()} | DISCONNECT WARNING | {e}")

if __name__ == "__main__":
    asyncio.run(main())
