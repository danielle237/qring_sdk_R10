#!/usr/bin/env python3
"""
EIS / COLMI R10 - TEMPERATURE 6 SAMPLES V3

Valide sur R10:
START = 69 0B 25 00 00 00 00 00 00 00 00 00 00 00 00 99
Reponse = 69 0B ERR RAW ...
Temperature = (RAW + 200) / 10.0
RAW == 0 : mesure pas encore disponible.

Objectif:
- une connexion BLE
- attendre la premiere temperature valide
- collecter 6 valeurs valides
- calculer la mediane
- STOP immediatement
- deconnexion
"""

import asyncio
import statistics
import time
from datetime import datetime
from bleak import BleakClient

MAC = "30:32:42:32:64:01"
WRITE_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
NOTIFY_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"

START_TEMP = bytes.fromhex(
    "69 0B 25 00 00 00 00 00 00 00 00 00 00 00 00 99"
)
STOP_TEMP = bytes.fromhex(
    "6A 0B 00 00 00 00 00 00 00 00 00 00 00 00 00 75"
)

TARGET_SAMPLES = 6
MEASURE_TIMEOUT = 40.0


def stamp():
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def hx(data):
    return " ".join(f"{b:02X}" for b in bytes(data))


async def main():
    client = BleakClient(MAC)
    samples = []
    done = asyncio.Event()
    t0 = None
    first_valid_time = None

    def notify(_sender, data):
        nonlocal first_valid_time

        raw_packet = bytes(data)

        if len(raw_packet) < 4:
            return
        if raw_packet[0] != 0x69 or raw_packet[1] != 0x0B:
            return

        err = raw_packet[2]
        raw_value = raw_packet[3]
        elapsed = time.perf_counter() - t0 if t0 else 0.0

        # Keep errors visible, but do not treat them as temperature.
        if err != 0:
            print(
                f"{stamp()} | TEMP ERROR | +{elapsed:.3f}s | "
                f"err={err} | HEX={hx(raw_packet)}",
                flush=True,
            )
            return

        # On this R10, zero is the waiting/not-ready state.
        if raw_value == 0:
            return

        temperature = (raw_value + 200) / 10.0

        if first_valid_time is None:
            first_valid_time = elapsed
            print(
                f"{stamp()} | FIRST VALID | +{elapsed:.3f}s | "
                f"raw={raw_value} (0x{raw_value:02X}) | "
                f"{temperature:.1f} C",
                flush=True,
            )

        if len(samples) < TARGET_SAMPLES:
            samples.append(temperature)
            print(
                f"{stamp()} | SAMPLE {len(samples)}/{TARGET_SAMPLES} | "
                f"raw={raw_value} (0x{raw_value:02X}) | "
                f"{temperature:.1f} C",
                flush=True,
            )

        if len(samples) >= TARGET_SAMPLES:
            done.set()

    print("=" * 72)
    print("EIS / COLMI R10 - TEMPERATURE 6 SAMPLES V3")
    print(f"TARGET          : {MAC}")
    print(f"TARGET SAMPLES  : {TARGET_SAMPLES}")
    print(f"MEASURE TIMEOUT : {MEASURE_TIMEOUT:.0f}s")
    print("=" * 72)

    try:
        connect_start = time.perf_counter()
        print(f"{stamp()} | CONNECT START")
        await client.connect()
        print(
            f"{stamp()} | CONNECT OK | "
            f"{time.perf_counter() - connect_start:.3f}s"
        )

        await client.start_notify(NOTIFY_UUID, notify)
        await asyncio.sleep(0.5)

        print(f"{stamp()} | TEMP START | {hx(START_TEMP)}")
        t0 = time.perf_counter()
        await client.write_gatt_char(WRITE_UUID, START_TEMP, response=False)

        try:
            await asyncio.wait_for(done.wait(), timeout=MEASURE_TIMEOUT)
        except asyncio.TimeoutError:
            print(
                f"{stamp()} | TEMP TIMEOUT | "
                f"{len(samples)}/{TARGET_SAMPLES} valid samples"
            )

        measure_time = time.perf_counter() - t0

        # Always STOP the measurement before leaving the GATT session.
        print(f"{stamp()} | TEMP STOP  | {hx(STOP_TEMP)}")
        await client.write_gatt_char(WRITE_UUID, STOP_TEMP, response=False)
        await asyncio.sleep(0.5)

        print("")
        print("=" * 72)
        print("RESULT")
        print(f"Valid samples : {samples}")

        if samples:
            median = statistics.median(samples)
            print(f"Median        : {median:.1f} C")
            if first_valid_time is not None:
                print(f"First valid   : {first_valid_time:.3f}s")
            print(f"Measure time  : {measure_time:.3f}s")
        else:
            print("No valid temperature received.")
            print(f"Measure time  : {measure_time:.3f}s")

        print("=" * 72)

    except Exception as e:
        print(f"{stamp()} | ERROR | {type(e).__name__}: {e}")

        # Best effort STOP if the connection still exists.
        try:
            if client.is_connected:
                await client.write_gatt_char(
                    WRITE_UUID, STOP_TEMP, response=False
                )
        except Exception:
            pass

    finally:
        try:
            if client.is_connected:
                print(f"{stamp()} | DISCONNECT START")
                await client.disconnect()
                print(f"{stamp()} | DISCONNECT OK")
        except Exception as e:
            print(
                f"{stamp()} | DISCONNECT WARNING | "
                f"{type(e).__name__}: {e}"
            )


if __name__ == "__main__":
    asyncio.run(main())
