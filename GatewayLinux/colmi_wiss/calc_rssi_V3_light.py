#!/usr/bin/env python3
"""
calc_rssi_V3_light.py
EIS / COLMI R10

Objectif :
- lire le RSSI de la connexion BLE GATT déjà ouverte par l'application Dany
- NE PAS lancer de scan BLE
- NE PAS ouvrir une deuxième connexion
- détecter automatiquement le handle HCI courant
- lire le RSSI via la commande HCI "Read RSSI"
- afficher la valeur brute et la médiane glissante
- ignorer les handles HCI transitoires tant que le RSSI n'est pas lisible
- mode faible impact : lectures espacées et backoff sur erreur
"""

import re
import subprocess
import time
import statistics
from collections import deque
from datetime import datetime

ADDRESS = "30:32:42:32:64:01"
RSSI_READ_INTERVAL_S = 3.0
DISCONNECTED_POLL_INTERVAL_S = 2.0
NEW_HANDLE_SETTLE_S = 1.5
RSSI_FAILURE_BACKOFF_S = 3.0
MEDIAN_WINDOW = 5
HCITOOL = "hcitool"


def now_str():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def run_command(args, timeout=5):
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        output = result.stdout or ""
        if result.stderr:
            output += "\n" + result.stderr
        return output.strip()
    except Exception:
        return ""


def get_connection_handle(address):
    output = run_command([HCITOOL, "con"])
    if not output:
        return None

    address_upper = address.upper()

    for line in output.splitlines():
        if address_upper not in line.upper():
            continue

        match = re.search(
            r"\bhandle\s+(\d+)\b",
            line,
            re.IGNORECASE,
        )
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                return None

    return None


def handle_to_little_endian_bytes(handle):
    return handle & 0xFF, (handle >> 8) & 0xFF


def signed_int8(value):
    return value - 256 if value >= 128 else value


def read_rssi(handle):
    low, high = handle_to_little_endian_bytes(handle)

    output = run_command(
        [
            HCITOOL,
            "cmd",
            "0x05",
            "0x0005",
            f"0x{low:02X}",
            f"0x{high:02X}",
        ]
    )

    if not output:
        return None, None, None

    event_match = re.search(
        r">\s*HCI Event:[^\n]*\n"
        r"\s*"
        r"([0-9A-Fa-f]{2})\s+"
        r"([0-9A-Fa-f]{2})\s+"
        r"([0-9A-Fa-f]{2})\s+"
        r"([0-9A-Fa-f]{2})\s+"
        r"([0-9A-Fa-f]{2})\s+"
        r"([0-9A-Fa-f]{2})\s+"
        r"([0-9A-Fa-f]{2})",
        output,
    )

    if not event_match:
        return None, None, None

    values = [int(x, 16) for x in event_match.groups()]

    status = values[3]
    if status != 0:
        return None, None, None

    returned_handle = values[4] | (values[5] << 8)
    if returned_handle != handle:
        return None, returned_handle, None

    raw_rssi = values[6]
    rssi_dbm = signed_int8(raw_rssi)

    return rssi_dbm, returned_handle, f"{raw_rssi:02X}"


def main():
    print("=" * 68)
    print("EIS - calc_rssi_V3 LIGHT")
    print(f"COLMI R10 : {ADDRESS}")
    print("Lecture RSSI de la connexion GATT existante")
    print("Mode faible impact : aucune connexion, aucun scan BLE")
    print(
        f"RSSI toutes les {RSSI_READ_INTERVAL_S:.1f}s | "
        f"poll déconnecté {DISCONNECTED_POLL_INTERVAL_S:.1f}s"
    )
    print("=" * 68)
    print("Ctrl+C pour arrêter.\n")

    rssi_history = deque(maxlen=MEDIAN_WINDOW)

    valid_handle = None
    was_connected = False

    # Permet d'éviter de frapper immédiatement hci0 lorsqu'une
    # nouvelle connexion Dany est encore en cours d'établissement.
    pending_handle = None
    pending_handle_since = None

    try:
        while True:
            candidate_handle = get_connection_handle(ADDRESS)

            # ------------------------------------------------
            # AUCUNE CONNEXION DANY
            # ------------------------------------------------
            if candidate_handle is None:
                if was_connected:
                    print(
                        f"{now_str()} | "
                        "DECONNECTE | plus de handle HCI valide"
                    )

                was_connected = False
                valid_handle = None
                pending_handle = None
                pending_handle_since = None
                rssi_history.clear()

                time.sleep(DISCONNECTED_POLL_INTERVAL_S)
                continue

            # ------------------------------------------------
            # NOUVEAU HANDLE :
            # laisser BlueZ/Bleak finir l'établissement GATT
            # avant toute commande HCI Read RSSI.
            # ------------------------------------------------
            if candidate_handle != valid_handle:
                if candidate_handle != pending_handle:
                    pending_handle = candidate_handle
                    pending_handle_since = time.monotonic()

                    time.sleep(0.25)
                    continue

                elapsed = time.monotonic() - pending_handle_since

                if elapsed < NEW_HANDLE_SETTLE_S:
                    time.sleep(
                        min(
                            0.25,
                            NEW_HANDLE_SETTLE_S - elapsed,
                        )
                    )
                    continue

            # ------------------------------------------------
            # UNE SEULE LECTURE RSSI
            # ------------------------------------------------
            rssi_dbm, _, raw_hex = read_rssi(candidate_handle)

            # Handle transitoire ou contrôleur occupé :
            # ne pas insister immédiatement.
            if rssi_dbm is None:
                time.sleep(RSSI_FAILURE_BACKOFF_S)
                continue

            # ------------------------------------------------
            # HANDLE CONFIRME PAR UNE VRAIE LECTURE RSSI
            # ------------------------------------------------
            if (
                not was_connected
                or candidate_handle != valid_handle
            ):
                valid_handle = candidate_handle
                pending_handle = None
                pending_handle_since = None
                was_connected = True
                rssi_history.clear()

                print(
                    f"{now_str()} | "
                    f"CONNECTE | handle={valid_handle}"
                )

            rssi_history.append(rssi_dbm)
            median_rssi = statistics.median(rssi_history)

            print(
                f"{now_str()} | "
                f"handle={valid_handle} | "
                f"RSSI={rssi_dbm:4d} dBm | "
                f"raw=0x{raw_hex} | "
                f"median{len(rssi_history)}="
                f"{median_rssi:5.1f} dBm"
            )

            # Faible impact : seulement une lecture toutes les 3 s.
            time.sleep(RSSI_READ_INTERVAL_S)

    except KeyboardInterrupt:
        print("\nArrêt calc_rssi_V3 LIGHT.")


if __name__ == "__main__":
    main()
