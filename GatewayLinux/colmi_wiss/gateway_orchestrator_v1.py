#!/usr/bin/env python3
"""
EIS / COLMI - ORCHESTRATEUR GATEWAY V1

Principe:
  1) lance test_reachable_v1.py
  2) REACHABLE (code retour 0) -> lance wiss_test_04_fast_one_connection.py
  3) NOT_AVAILABLE (code retour 1) -> s'arrête immédiatement
  4) erreur technique -> ne lance PAS V4

Les deux programmes restent indépendants.
"""

import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

BASE = Path("/root/colmi_wiss")
REACHABLE_SCRIPT = BASE / "test_reachable_v1.py"
MEASURE_SCRIPT = BASE / "wiss_test_04_fast_one_connection.py"

# Utilise exactement le même Python que celui qui lance l'orchestrateur.
PYTHON = sys.executable


def ts():
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def log(msg=""):
    print(f"{ts()} | {msg}", flush=True)


def run_script(path):
    return subprocess.run([PYTHON, str(path)], check=False)


def main():
    t0 = time.perf_counter()

    log("=" * 68)
    log("EIS / COLMI - ORCHESTRATEUR GATEWAY V1")
    log(f"PYTHON : {PYTHON}")
    log(f"REACH  : {REACHABLE_SCRIPT}")
    log(f"MEASURE: {MEASURE_SCRIPT}")
    log("=" * 68)

    for p in (REACHABLE_SCRIPT, MEASURE_SCRIPT):
        if not p.exists():
            log(f"ERROR | fichier absent : {p}")
            return 2

    log("")
    log("=== ETAPE 1 : REACHABILITY ===")
    reach = run_script(REACHABLE_SCRIPT)

    log("")
    log(f"REACHABILITY | returncode={reach.returncode}")

    if reach.returncode == 1:
        log("DECISION | NOT_AVAILABLE -> mesures NON lancees")
        log(f"TOTAL ORCHESTRATEUR | {time.perf_counter() - t0:.3f}s")
        return 0

    if reach.returncode != 0:
        log("DECISION | ERREUR TECHNIQUE reachability -> mesures NON lancees")
        log(f"TOTAL ORCHESTRATEUR | {time.perf_counter() - t0:.3f}s")
        return 2

    log("DECISION | REACHABLE -> lancement V4")
    log("")
    log("=== ETAPE 2 : INFO / BATTERY / HR / SpO2 ===")

    measure = run_script(MEASURE_SCRIPT)

    log("")
    log(f"V4 | returncode={measure.returncode}")
    log(f"TOTAL ORCHESTRATEUR | {time.perf_counter() - t0:.3f}s")

    if measure.returncode != 0:
        log("RESULTAT | V4 terminee avec erreur")
        return measure.returncode

    log("RESULTAT | cycle termine")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
