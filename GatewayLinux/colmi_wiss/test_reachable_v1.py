#!/usr/bin/env python3
# EIS / COLMI R10 - TEST REACHABILITY V1
#
# But:
#   Déterminer rapidement si la R10 est visible au niveau radio BLE,
#   SANS connexion GATT, SANS INFO/BATTERY, SANS HR/SpO2, SANS MQTT.
#
# Résultat:
#   REACHABLE     = la MAC cible a été vue en advertising
#   NOT_AVAILABLE = la MAC cible n'a pas été vue pendant la fenêtre de test
#
# Important:
#   Ce test mesure la visibilité radio/advertising, pas la capacité à terminer
#   une connexion GATT complète.

import asyncio
import time
from datetime import datetime

from bleak import BleakScanner

MAC = "30:32:42:32:64:01"
NAME = "COLMI R10_6401"

# On commence volontairement avec 5 secondes.
# Après essais réels, on pourra tester 3 s, 2 s, etc.
REACH_TIMEOUT = 5.0


def ts():
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def log(msg=""):
    print(f"{ts()} | {msg}", flush=True)


async def main():
    target = MAC.lower()
    found = asyncio.Event()
    result = {
        "name": None,
        "address": None,
        "rssi": None,
        "first_seen_s": None,
    }

    t0 = time.perf_counter()

    def detection_callback(device, advertisement_data):
        if device.address.lower() != target:
            return

        if result["first_seen_s"] is None:
            result["first_seen_s"] = time.perf_counter() - t0
            result["name"] = device.name or advertisement_data.local_name
            result["address"] = device.address
            result["rssi"] = advertisement_data.rssi

            log(
                f"TARGET SEEN | {result['address']} | "
                f"name={result['name']} | RSSI={result['rssi']} dBm | "
                f"after={result['first_seen_s']:.3f}s"
            )
            found.set()

    scanner = BleakScanner(detection_callback)

    log("=" * 68)
    log("EIS / COLMI R10 - REACHABILITY TEST V1")
    log(f"TARGET  : {NAME} | {MAC}")
    log(f"WINDOW  : {REACH_TIMEOUT:.1f}s")
    log("MODE    : BLE advertising only - NO GATT connection")
    log("=" * 68)

    try:
        await scanner.start()

        try:
            await asyncio.wait_for(found.wait(), timeout=REACH_TIMEOUT)
        except asyncio.TimeoutError:
            pass

    finally:
        try:
            await scanner.stop()
        except Exception as e:
            log(f"SCAN STOP WARNING | {type(e).__name__}: {e}")

    total = time.perf_counter() - t0

    log("")
    log("=== RESULT ===")

    if found.is_set():
        log("STATUS     : REACHABLE")
        log(f"FIRST SEEN : {result['first_seen_s']:.3f}s")
        log(f"RSSI       : {result['rssi']} dBm")
        log(f"TOTAL      : {total:.3f}s")
        return 0

    log("STATUS     : NOT_AVAILABLE")
    log(f"TOTAL      : {total:.3f}s")
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\nCtrl+C")
        raise SystemExit(130)
