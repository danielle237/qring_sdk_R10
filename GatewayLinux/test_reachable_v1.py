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

import argparse
import asyncio
import json
import os
import socket
import time
from datetime import datetime

from bleak import BleakScanner

MAC = "30:32:42:32:64:01"
NAME = "COLMI R10_6401"

# On commence volontairement avec 5 secondes.
# Après essais réels, on pourra tester 3 s, 2 s, etc.
REACH_TIMEOUT = 5.0

# Paramètres lus dans un .env (le même que la GATEWAY RHM) : RING_MAC, RING_NAME, GATEWAY_NAME,
# REACH_WINDOW, REACH_JSON (1 = ligne RESULT_JSON). Fichier cherché dans l'ordre :
#   $REACH_ENV_FILE, .env à côté de ce script, /root/gateway_rhm/.env
# Les options en ligne de commande restent prioritaires sur le .env.
def load_env():
    paths = [os.getenv("REACH_ENV_FILE"), os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
             "/root/gateway_rhm/.env"]
    for path in paths:
        if path and os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    v = v.split(" #")[0].strip().strip('"').strip("'")
                    os.environ.setdefault(k.strip(), v)
            return path
    return None


ENV_FILE = load_env()
MAC = os.getenv("RING_MAC") or MAC
NAME = os.getenv("RING_NAME") or NAME
REACH_TIMEOUT = float(os.getenv("REACH_WINDOW") or REACH_TIMEOUT)

# Options (facultatives, valeurs par défaut = .env, sinon comportement d'origine) :
#   --mac 30:32:42:32:64:01  --name "COLMI R10_6401"  --window 5  --json
# --json ajoute une dernière ligne « RESULT_JSON {...} » lue par la GATEWAY RHM.
ap = argparse.ArgumentParser(description="Test de portée BLE (écoute seule) d'une bague COLMI")
ap.add_argument("--mac", default=MAC)
ap.add_argument("--name", default=None)
ap.add_argument("--window", type=float, default=REACH_TIMEOUT)
ap.add_argument("--json", action="store_true", default=os.getenv("REACH_JSON", "0") in ("1", "true", "yes"))
ap.add_argument("--gateway", default=os.getenv("GATEWAY_NAME") or socket.gethostname(),
                help="nom de la gateway (affiché et renvoyé dans le résultat)")
ARGS = ap.parse_args()
if ARGS.mac.upper() != MAC.upper() and ARGS.name is None:
    NAME = ARGS.mac.upper()   # autre bague donnée en option : son nom n'est pas connu
MAC = ARGS.mac.upper()
NAME = ARGS.name or NAME
REACH_TIMEOUT = ARGS.window


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
    log(f"GATEWAY : {ARGS.gateway}")
    log(f"CONFIG  : {ENV_FILE or 'aucun .env (valeurs du script)'}")
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
        log(f"GATEWAY    : {ARGS.gateway}")
        log("STATUS     : REACHABLE")
        log(f"FIRST SEEN : {result['first_seen_s']:.3f}s")
        log(f"RSSI       : {result['rssi']} dBm")
        log(f"TOTAL      : {total:.3f}s")
        if ARGS.json:
            print("RESULT_JSON " + json.dumps({"status": "REACHABLE", "gateway": ARGS.gateway, "mac": MAC, "name": result["name"],
                                               "rssi": result["rssi"], "first_seen": round(result["first_seen_s"], 3),
                                               "total": round(total, 3)}), flush=True)
        return 0

    log(f"GATEWAY    : {ARGS.gateway}")
    log("STATUS     : NOT_AVAILABLE")
    log(f"TOTAL      : {total:.3f}s")
    if ARGS.json:
        print("RESULT_JSON " + json.dumps({"status": "NOT_AVAILABLE", "gateway": ARGS.gateway, "mac": MAC, "rssi": None,
                                           "total": round(total, 3)}), flush=True)
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\nCtrl+C")
        raise SystemExit(130)
