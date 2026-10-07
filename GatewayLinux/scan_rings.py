#!/usr/bin/env python3
"""
GATEWAY RHM Linux — écoute passive des bagues (aucune connexion), lancée par gateway_multi.py.

Écoute le Bluetooth par fenêtres de quelques secondes et écrit une ligne JSON par fenêtre :
  {"ts": 1790871236, "window": 4.0, "seen": {"30:32:42:32:64:01": {"rssi": -71, "max": -66, "n": 9, "name": "R10_6401"}}}

Partage du Bluetooth avec les mesures (une seule chose à la fois sur le boîtier) :
  * verrou <run>/bt.lock pendant chaque fenêtre d'écoute ;
  * dès qu'une mesure attend (fichier <run>/want-*), l'écoute s'arrête et lui laisse le verrou.

À lancer avec un Python qui a bleak (python3.14) :
  python3.14 scan_rings.py --run /run/gateway-rhm --macs-file /run/gateway-rhm/macs.txt
"""
import argparse
import asyncio
import fcntl
import glob
import json
import os
import statistics
import subprocess
import sys
import time

from bleak import BleakScanner


def want_pending(run):
    return bool(glob.glob(os.path.join(run, "want-*")))


def read_macs(path):
    try:
        with open(path) as f:
            return {l.strip().upper() for l in f if l.strip()}
    except OSError:
        return set()


def out(obj):
    print(json.dumps(obj), flush=True)


async def listen(macs, window, run):
    """Une fenêtre d'écoute ; s'arrête plus tôt si une mesure attend. → (vu, durée réelle)."""
    found = {}

    def cb(dev, adv):
        a = (dev.address or "").upper()
        if a in macs:
            e = found.setdefault(a, {"vals": [], "name": dev.name or adv.local_name or ""})
            e["vals"].append(adv.rssi)

    t0 = time.time()
    async with BleakScanner(cb):
        while time.time() - t0 < window:
            await asyncio.sleep(0.25)
            if want_pending(run):
                break
    return found, time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="/run/gateway-rhm")
    ap.add_argument("--macs-file", required=True)
    ap.add_argument("--window", type=float, default=4.0)
    ap.add_argument("--pause", type=float, default=1.0)
    a = ap.parse_args()
    os.makedirs(a.run, exist_ok=True)
    lock_path = os.path.join(a.run, "bt.lock")
    errors = 0
    while True:
        macs = read_macs(a.macs_file)
        if not macs or want_pending(a.run):
            time.sleep(0.5)
            continue
        f = open(lock_path, "a+")
        try:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                time.sleep(0.5)       # une mesure tient le Bluetooth
                continue
            if want_pending(a.run):
                continue
            try:
                found, dur = asyncio.run(listen(macs, a.window, a.run))
                errors = 0
            except Exception as e:
                errors += 1
                out({"ts": int(time.time()), "error": str(e)[:200]})
                if errors >= 2:
                    # Adaptateur éteint (après un redémarrage du service) : on le rallume
                    subprocess.run(["bluetoothctl", "power", "on"], capture_output=True, timeout=10)
                time.sleep(min(10, 2 * errors))
                continue
        finally:
            try:
                fcntl.flock(f, fcntl.LOCK_UN)
            except OSError:
                pass
            f.close()
        seen = {m: {"rssi": round(statistics.median(e["vals"])), "max": max(e["vals"]), "n": len(e["vals"]),
                    "name": e["name"]} for m, e in found.items() if e["vals"]}
        # Fenêtre coupée très tôt par une mesure : pas de conclusion « non entendue »
        out({"ts": int(time.time()), "window": round(dur, 1), "partial": dur < a.window * 0.5, "seen": seen})
        time.sleep(a.pause)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
