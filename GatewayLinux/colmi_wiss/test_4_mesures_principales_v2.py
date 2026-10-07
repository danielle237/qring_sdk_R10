#!/usr/bin/env python3
"""
EIS / COLMI R10
4 MAIN MEASUREMENTS - ONE BLE CONNECTION
HR -> SpO2 -> Temperature -> HRV

No reachability scan.
Each measurement has its own START and STOP.
Six non-zero samples per measurement.
Error policy V2:
- protocol error=1 => NON_WORN, STOP current measurement and EXIT immediately
- connect failure => CONNECT_FAILED
- GATT loss => CONNECTION_LOST
- timeout with GATT alive => MEASUREMENT_TIMEOUT
- other measurement error => MEASUREMENT_ERROR
The measurement script does NOT launch reachability.
Temperature conversion follows QRing: (raw + 200) / 10.
HRV unit intentionally left unknown.
"""

import asyncio
import statistics
import time
from datetime import datetime
from bleak import BleakClient
from bleak.exc import BleakDeviceNotFoundError

MAC = "30:32:42:32:64:01"
NAME = "COLMI R10_6401"

WRITE_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
NOTIFY_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

CMD_START = 0x69
CMD_STOP = 0x6A

HR = 0x01
SPO2 = 0x03
TEMP = 0x0B
HRV = 0x0A

TARGET_SAMPLES = 6
MEASURE_TIMEOUT = 40.0
CONNECT_TIMEOUT = 15.0


def ts():
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def hx(data):
    return " ".join(f"{b:02X}" for b in bytes(data))


def make_packet(cmd, payload):
    p = bytearray(16)
    p[0] = cmd
    p[1:1 + len(payload)] = bytes(payload)
    p[15] = sum(p[:15]) & 0xFF
    return bytes(p)


# HR, SpO2 and HRV: validated Linux V1 protocol, Action.START = 0x01
def start_v1(kind):
    return make_packet(CMD_START, [kind, 0x01])


def stop_v1(kind):
    return make_packet(CMD_STOP, [kind, 0x00, 0x00])


# Temperature: validated exact R10 / QRing protocol
def start_temperature():
    return make_packet(CMD_START, [TEMP, 0x25, 0x00])


def stop_temperature():
    return make_packet(CMD_STOP, [TEMP, 0x00, 0x00])


MEASURES = [
    {
        "key": "hr",
        "label": "HEART RATE",
        "kind": HR,
        "start": start_v1(HR),
        "stop": stop_v1(HR),
        "convert": lambda raw: raw,
        "unit": "bpm",
    },
    {
        "key": "spo2",
        "label": "SpO2",
        "kind": SPO2,
        "start": start_v1(SPO2),
        "stop": stop_v1(SPO2),
        "convert": lambda raw: raw,
        "unit": "%",
    },
    {
        "key": "temperature",
        "label": "TEMPERATURE",
        "kind": TEMP,
        "start": start_temperature(),
        "stop": stop_temperature(),
        "convert": lambda raw: round((raw + 200) / 10.0, 1),
        "unit": "C",
    },
    {
        "key": "hrv",
        "label": "HRV",
        "kind": HRV,
        "start": start_v1(HRV),
        "stop": stop_v1(HRV),
        "convert": lambda raw: raw,
        "unit": "unknown",
    },
]


async def measure_one(client, cfg):
    samples = []
    raw_samples = []
    error_code = None
    first_valid_s = None
    first_clock = None
    last_clock = None
    started = False
    stop_sent = False
    timed_out = False
    exception = None
    done = asyncio.Event()
    measure_start = None

    def notify(_sender, data):
        nonlocal error_code, first_valid_s, first_clock, last_clock

        packet = bytes(data)
        if len(packet) != 16:
            return
        if packet[0] != CMD_START or packet[1] != cfg["kind"]:
            return

        err = packet[2]
        raw_value = packet[3]

        if err != 0:
            error_code = err
            elapsed = time.perf_counter() - measure_start if measure_start else 0.0
            print(
                f"{ts()} | {cfg['label']} ERROR | +{elapsed:.3f}s | "
                f"code={err} | HEX={hx(packet)}",
                flush=True,
            )
            done.set()
            return

        if raw_value == 0:
            return

        now = time.perf_counter()
        if first_clock is None:
            first_clock = now
            first_valid_s = now - measure_start
            print(f"{ts()} | {cfg['label']} FIRST VALID | +{first_valid_s:.3f}s", flush=True)

        if len(samples) < TARGET_SAMPLES:
            value = cfg["convert"](raw_value)
            raw_samples.append(raw_value)
            samples.append(value)
            last_clock = now
            print(
                f"{ts()} | {cfg['label']} SAMPLE "
                f"{len(samples)}/{TARGET_SAMPLES} | {value} {cfg['unit']}",
                flush=True,
            )

        if len(samples) >= TARGET_SAMPLES:
            done.set()

    print()
    print("=" * 70)
    print(cfg["label"])
    print(f"START : {hx(cfg['start'])}")
    print(f"STOP  : {hx(cfg['stop'])}")
    print("=" * 70)

    try:
        await client.start_notify(NOTIFY_UUID, notify)
        await asyncio.sleep(0.25)

        measure_start = time.perf_counter()
        print(f"{ts()} | {cfg['label']} START")
        await client.write_gatt_char(WRITE_UUID, cfg["start"], response=False)
        started = True

        try:
            await asyncio.wait_for(done.wait(), timeout=MEASURE_TIMEOUT)
        except asyncio.TimeoutError:
            timed_out = True
            print(
                f"{ts()} | {cfg['label']} TIMEOUT | "
                f"{len(samples)}/{TARGET_SAMPLES} samples",
                flush=True,
            )

        measurement_s = time.perf_counter() - measure_start

    except Exception as e:
        exception = e
        measurement_s = (
            time.perf_counter() - measure_start if measure_start is not None else None
        )
        print(f"{ts()} | {cfg['label']} EXCEPTION | {type(e).__name__}: {e}", flush=True)

    finally:
        # STOP is attempted before any exit, whenever GATT is still alive.
        if started and client.is_connected:
            try:
                print(f"{ts()} | {cfg['label']} STOP")
                await client.write_gatt_char(WRITE_UUID, cfg["stop"], response=False)
                stop_sent = True
                await asyncio.sleep(0.5)
            except Exception as e:
                if exception is None:
                    exception = e
                print(f"{ts()} | {cfg['label']} STOP ERROR | {type(e).__name__}: {e}", flush=True)

        try:
            if client.is_connected:
                await client.stop_notify(NOTIFY_UUID)
        except Exception:
            pass

    window_s = None
    if first_clock is not None and last_clock is not None:
        window_s = last_clock - first_clock

    if exception is not None or not client.is_connected:
        reason = "CONNECTION_LOST"
    elif error_code == 1:
        reason = "NON_WORN"
    elif error_code is not None:
        reason = "MEASUREMENT_ERROR"
    elif timed_out or len(samples) < TARGET_SAMPLES:
        reason = "MEASUREMENT_TIMEOUT"
    else:
        reason = "SUCCESS"

    ok = reason == "SUCCESS"

    return {
        "ok": ok,
        "reason": reason,
        "samples": samples,
        "raw_samples": raw_samples,
        "median": statistics.median(samples) if samples else None,
        "error": error_code,
        "first_valid_s": first_valid_s,
        "samples_window_s": window_s,
        "measurement_s": measurement_s,
        "stop_sent": stop_sent,
    }

async def main():
    program_start = time.perf_counter()
    results = {}
    final_status = "UNKNOWN"
    failed_measure = None
    client = BleakClient(MAC, timeout=CONNECT_TIMEOUT)

    print("=" * 70)
    print("EIS / COLMI R10 - 4 MAIN MEASUREMENTS V2")
    print(f"TARGET : {NAME} | {MAC}")
    print("MODE   : ONE BLE CONNECTION")
    print("ORDER  : HR -> SpO2 -> Temperature -> HRV")
    print("REACH  : disabled")
    print("POLICY : exit immediately on NON_WORN / GATT loss / timeout / error")
    print("=" * 70)

    try:
        c0 = time.perf_counter()
        print(f"{ts()} | CONNECT START")
        try:
            await client.connect()
        except (BleakDeviceNotFoundError, asyncio.TimeoutError) as e:
            final_status = "CONNECT_FAILED"
            print(f"{ts()} | CONNECT FAILED | {type(e).__name__}: {e}")
            return
        except Exception as e:
            final_status = "CONNECT_FAILED"
            print(f"{ts()} | CONNECT FAILED | {type(e).__name__}: {e}")
            return

        print(f"{ts()} | CONNECT OK | {time.perf_counter() - c0:.3f}s")

        for cfg in MEASURES:
            if not client.is_connected:
                final_status = "CONNECTION_LOST"
                failed_measure = cfg["key"]
                print(f"{ts()} | CONNECTION LOST before {cfg['label']} | EXIT")
                break

            result = await measure_one(client, cfg)
            results[cfg["key"]] = result

            if not result["ok"]:
                final_status = result["reason"]
                failed_measure = cfg["key"]
                print()
                print(
                    f"{ts()} | EARLY EXIT | measure={cfg['label']} "
                    f"| reason={final_status}"
                )
                print("Remaining measurements are NOT executed.")
                break
        else:
            final_status = "SUCCESS"

    finally:
        total_s = time.perf_counter() - program_start

        print()
        print("=" * 70)
        print("FINAL RESULT")
        print("=" * 70)

        for cfg in MEASURES:
            r = results.get(cfg["key"])
            if r is None:
                print(f"{cfg['label']:<12}: NOT EXECUTED")
            else:
                print(
                    f"{cfg['label']:<12}: "
                    f"ok={r.get('ok')} | "
                    f"samples={r.get('samples')} | "
                    f"median={r.get('median')} | "
                    f"error={r.get('error')} | "
                    f"reason={r.get('reason')}"
                )

        print("-" * 70)
        print(f"STATUS       : {final_status}")
        print(f"FAILED AT    : {failed_measure}")
        print(f"TOTAL        : {total_s:.3f}s")

        # Hint for Dany's gateway/broker orchestration.
        if final_status in ("CONNECT_FAILED", "CONNECTION_LOST"):
            print("NEXT ACTION  : REACHABILITY_RECOMMENDED")
        elif final_status == "NON_WORN":
            print("NEXT ACTION  : NO_REACHABILITY - ring responded, measurement conditions invalid")
        elif final_status in ("MEASUREMENT_TIMEOUT", "MEASUREMENT_ERROR"):
            print("NEXT ACTION  : NO_AUTOMATIC_REACHABILITY - report measurement failure")
        elif final_status == "SUCCESS":
            print("NEXT ACTION  : NONE")

        print("=" * 70)

        if client.is_connected:
            try:
                print(f"{ts()} | DISCONNECT START")
                await client.disconnect()
                print(f"{ts()} | DISCONNECT OK")
            except Exception as e:
                print(f"{ts()} | DISCONNECT WARNING | {type(e).__name__}: {e}")

if __name__ == "__main__":
    asyncio.run(main())
