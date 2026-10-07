#!/usr/bin/env python3
"""
EIS / COLMI R10
TEMPERATURE ONLY - ONE BLE CONNECTION
(extrait de colmi_4_mesures_v3_clean.py : même protocole, même sortie, seulement la température)

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

import argparse
import asyncio
import json
import re
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
        "key": "temperature",
        "label": "TEMPERATURE",
        "kind": TEMP,
        "start": start_temperature(),
        "stop": stop_temperature(),
        "convert": lambda raw: round((raw + 200) / 10.0, 1),
        "unit": "C",
    },
]


async def measure_one(client, cfg, disconnect_event):
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

        done_task = asyncio.create_task(done.wait())
        disconnect_task = asyncio.create_task(disconnect_event.wait())

        try:
            finished, pending = await asyncio.wait(
                {done_task, disconnect_task},
                timeout=MEASURE_TIMEOUT,
                return_when=asyncio.FIRST_COMPLETED,
            )

            for task in pending:
                task.cancel()

            if disconnect_task in finished and disconnect_event.is_set():
                print(
                    f"{ts()} | {cfg['label']} ABORT | GATT connection lost",
                    flush=True,
                )
            elif done_task in finished and done.is_set():
                pass
            else:
                timed_out = True
                print(
                    f"{ts()} | {cfg['label']} TIMEOUT | "
                    f"{len(samples)}/{TARGET_SAMPLES} samples",
                    flush=True,
                )
        finally:
            for task in (done_task, disconnect_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(done_task, disconnect_task, return_exceptions=True)

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

    # Classification V3: never confuse non-worn, timeout and radio/GATT loss.
    if disconnect_event.is_set() or not client.is_connected:
        reason = "CONNECTION_LOST"
    elif error_code == 1:
        reason = "NON_WORN"
    elif error_code is not None:
        reason = "MEASUREMENT_ERROR"
    elif exception is not None:
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

# ---------------------------------------------------------------- options (Gateway RHM) — facultatives :
# sans option : MAC ci-dessus
#   --mac 30:32:42:32:64:01   bague à mesurer
#   --name "COLMI R10_6401"   nom affiché
#   --json                    ajoute à la fin une ligne « RESULT_JSON {...} » (lue par gateway_linux.py)
def parse_args():
    global MAC, NAME
    ap = argparse.ArgumentParser(description="COLMI R10 : température seule")
    ap.add_argument("--mac")
    ap.add_argument("--name")
    ap.add_argument("--only", help="ignoré (compatibilité) : toujours la température")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.mac:
        h = re.sub(r"[^0-9A-Fa-f]", "", a.mac)
        if len(h) != 12:
            ap.error(f"MAC invalide : {a.mac}")
        MAC = ":".join(h[i:i + 2] for i in range(0, 12, 2)).upper()
        if not a.name:
            NAME = f"COLMI {MAC}"
    if a.name:
        NAME = a.name
    return a


async def main(json_out=False):
    program_start = time.perf_counter()
    results = {}
    final_status = "UNKNOWN"
    failed_measure = None
    disconnect_event = asyncio.Event()
    disconnect_time = {"clock": None}

    def on_disconnect(_client):
        disconnect_time["clock"] = time.perf_counter()
        print(f"{ts()} | *** GATT DISCONNECTED ***", flush=True)
        disconnect_event.set()

    client = BleakClient(
        MAC,
        timeout=CONNECT_TIMEOUT,
        disconnected_callback=on_disconnect,
    )

    print("=" * 70)
    print("EIS / COLMI R10 - TEMPERATURE V3")
    print(f"TARGET : {NAME} | {MAC}")
    print("MODE   : ONE BLE CONNECTION")
    print("ORDER  : " + " -> ".join(m["label"] for m in MEASURES))
    print("REACH  : disabled")
    print("POLICY : immediate GATT-loss detection + distinct NON_WORN / TIMEOUT / ERROR")
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

            # Event is clear at the start of a healthy connected cycle.
            disconnect_event.clear()
            result = await measure_one(client, cfg, disconnect_event)
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
        if json_out:
            out = {"status": final_status, "failed_at": failed_measure, "total_s": round(total_s, 3), "mac": MAC,
                   "results": {k: {"ok": r.get("ok"), "reason": r.get("reason"), "samples": r.get("samples"),
                                   "median": r.get("median"), "error": r.get("error")} for k, r in results.items()}}
            print("RESULT_JSON " + json.dumps(out), flush=True)

        if client.is_connected:
            try:
                print(f"{ts()} | DISCONNECT START (intentional)")
                await client.disconnect()
                print(f"{ts()} | DISCONNECT OK")
            except Exception as e:
                print(f"{ts()} | DISCONNECT WARNING | {type(e).__name__}: {e}")

if __name__ == "__main__":
    _args = parse_args()
    asyncio.run(main(json_out=_args.json))
