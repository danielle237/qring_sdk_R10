#!/usr/bin/env python3
"""
calc_rssi_V1.py
EIS / COLMI R10

Objectif :
- lire le RSSI de la connexion BLE GATT déjà ouverte par l'application Dany
- NE PAS lancer de scan BLE
- NE PAS ouvrir une deuxième connexion
- détecter automatiquement le handle HCI courant
- lire le RSSI via la commande HCI "Read RSSI"
- afficher la valeur brute et la médiane glissante
"""

import re
import subprocess
import time
import statistics
from collections import deque
from datetime import datetime

ADDRESS = "30:32:42:32:64:01"
READ_INTERVAL_S = 1.0
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
    print("EIS - calc_rssi_V1")
    print(f"COLMI R10 : {ADDRESS}")
    print("Lecture RSSI de la connexion GATT existante")
    print("Aucun scan BLE - aucune nouvelle connexion")
    print("=" * 68)
    print("Ctrl+C pour arrêter.\n")

    rssi_history = deque(maxlen=MEDIAN_WINDOW)
    last_handle = None
    was_connected = False

    try:
        while True:
            handle = get_connection_handle(ADDRESS)

            if handle is None:
                if was_connected:
                    print(
                        f"{now_str()} | "
                        "DECONNECTE | plus de handle HCI"
                    )

                was_connected = False
                last_handle = None
                rssi_history.clear()

                time.sleep(READ_INTERVAL_S)
                continue

            if not was_connected or handle != last_handle:
                print(
                    f"{now_str()} | "
                    f"CONNECTE | handle={handle}"
                )
                rssi_history.clear()

            was_connected = True
            last_handle = handle

            rssi_dbm, _, raw_hex = read_rssi(handle)

            if rssi_dbm is None:
                print(
                    f"{now_str()} | "
                    f"handle={handle} | RSSI indisponible"
                )
                time.sleep(READ_INTERVAL_S)
                continue

            rssi_history.append(rssi_dbm)
            median_rssi = statistics.median(rssi_history)

            print(
                f"{now_str()} | "
                f"handle={handle} | "
                f"RSSI={rssi_dbm:4d} dBm | "
                f"raw=0x{raw_hex} | "
                f"median{len(rssi_history)}="
                f"{median_rssi:5.1f} dBm"
            )

            time.sleep(READ_INTERVAL_S)

    except KeyboardInterrupt:
        print("\nArrêt calc_rssi_V1.")


if __name__ == "__main__":
    main()
