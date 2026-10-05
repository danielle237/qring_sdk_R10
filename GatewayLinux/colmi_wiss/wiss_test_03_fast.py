#!/usr/bin/env python3
# WISS / COLMI SIMPLE - TEST 03 FAST
# - INFO/BATTERY, HR et SpO2 en transactions séparées
# - restart bluetooth après chaque transaction
# - RAW BLE dans le fichier log uniquement
# - temps détaillés dans le résultat final

import asyncio
import subprocess
import time
import json
from datetime import datetime
from pathlib import Path

from bleak import BleakClient
from bleak.exc import BleakDeviceNotFoundError
import paho.mqtt.client as mqtt

MAC = "30:32:42:32:64:01"
NAME = "COLMI R10_6401"

RX = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
TX = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"
HW = "00002A27-0000-1000-8000-00805F9B34FB"
FW = "00002A26-0000-1000-8000-00805F9B34FB"

CMD_BATTERY = 0x03
CMD_START = 0x69
CMD_STOP = 0x6A
HR = 0x01
SPO2 = 0x03

CONNECT_TIMEOUT = 15
MEASURE_TIMEOUT = 35
TARGET_SAMPLES = 6

# MQTT supervision
MQTT_HOST = "51.83.40.138"
MQTT_PORT = 1883
MQTT_USER = "tvclient"
MQTT_PASSWORD = "tvclient210367@Tunis"
MQTT_TOPIC = "/test_wiss2/R10_6401/result"

# Le log est créé dans le MEME répertoire que ce script.
SCRIPT_DIR = Path(__file__).resolve().parent
LOGFILE = SCRIPT_DIR / f"wiss_test_02_{datetime.now():%Y%m%d_%H%M%S}.log"


def ts():
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def _write_log(line):
    with LOGFILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def log(msg=""):
    """Affiche à l'écran ET écrit dans le fichier log."""
    line = f"{ts()} | {msg}"
    print(line, flush=True)
    _write_log(line)


def log_raw(msg):
    """RAW BLE : écrit dans le fichier log uniquement."""
    line = f"{ts()} | {msg}"
    _write_log(line)


def hx(data):
    return " ".join(f"{b:02X}" for b in data)


def packet(command, data=b""):
    p = bytearray(16)
    p[0] = command
    p[1:1 + len(data)] = data
    p[15] = sum(p) & 0xFF
    return bytes(p)


BATTERY_PACKET = packet(CMD_BATTERY)


def start_packet(kind):
    return packet(CMD_START, bytes([kind, 0x01]))


def stop_packet(kind):
    return packet(CMD_STOP, bytes([kind, 0x00, 0x00]))


def fmt_s(value):
    return "N/A" if value is None else f"{value:.3f} s"


async def restart_bt(reason):
    log(f"BT RESTART | {reason}")
    t0 = time.perf_counter()
    p = await asyncio.create_subprocess_exec("systemctl", "restart", "bluetooth")
    await p.wait()
    elapsed = time.perf_counter() - t0
    log(f"BT RESTART | rc={p.returncode} | {elapsed:.3f}s")
    await asyncio.sleep(2)
    return elapsed + 2.0


async def disconnect(client, label):
    if client is None:
        return None

    t0 = time.perf_counter()
    try:
        if client.is_connected:
            log(f"{label} | DISCONNECT START")
            await asyncio.wait_for(client.disconnect(), 10)
        elapsed = time.perf_counter() - t0
        log(f"{label} | CONNECTED={client.is_connected} | disconnect={elapsed:.3f}s")
        return elapsed
    except Exception as e:
        elapsed = time.perf_counter() - t0
        log(f"{label} | DISCONNECT ERROR | {type(e).__name__}: {e}")
        return elapsed


async def connect(label):
    log(f"{label} | CONNECT START | {MAC}")
    c = BleakClient(MAC)
    t0 = time.perf_counter()
    await asyncio.wait_for(c.connect(), CONNECT_TIMEOUT)
    elapsed = time.perf_counter() - t0
    log(f"{label} | CONNECT OK | {elapsed:.3f}s")
    return c, elapsed


async def info_battery():
    client = None
    result = None
    cycle_start = time.perf_counter()
    connect_s = None
    read_s = None
    disconnect_s = None
    reset_s = None

    log("\n=== 1. INFO + BATTERY ===")

    try:
        client, connect_s = await connect("INFO")
        read_start = time.perf_counter()

        hw = bytes(await client.read_gatt_char(HW)).decode(errors="replace").rstrip("\x00")
        fw = bytes(await client.read_gatt_char(FW)).decode(errors="replace").rstrip("\x00")
        log(f"INFO | HW={hw}")
        log(f"INFO | FW={fw}")

        done = asyncio.Event()
        battery = {"level": None, "charging": None}

        def notify(_sender, data):
            raw = bytes(data)
            log_raw(f"INFO | RX RAW | {hx(raw)}")
            if len(raw) == 16 and raw[0] == CMD_BATTERY:
                battery["level"] = raw[1]
                battery["charging"] = bool(raw[2])
                done.set()

        await client.start_notify(TX, notify)
        log_raw(f"INFO | TX BATTERY | {hx(BATTERY_PACKET)}")
        await client.write_gatt_char(RX, BATTERY_PACKET, response=False)

        try:
            await asyncio.wait_for(done.wait(), 5)
        except asyncio.TimeoutError:
            log("INFO | BATTERY TIMEOUT")

        read_s = time.perf_counter() - read_start
        log(f"INFO | BATTERY={battery['level']}% | CHARGING={battery['charging']}")
        log(f"INFO | READ TIME={read_s:.3f}s")

        result = {
            "hw": hw,
            "fw": fw,
            **battery,
            "connect_s": connect_s,
            "read_s": read_s,
        }

    except (BleakDeviceNotFoundError, asyncio.TimeoutError) as e:
        log(f"INFO | NOT AVAILABLE | {type(e).__name__}: {e}")
        log("FR : La bague est-elle hors portée ou déchargée ?")
        log("EN : Is the ring out of range or discharged?")
    except Exception as e:
        log(f"INFO | ERROR | {type(e).__name__}: {e}")
        log("FR : La bague est-elle hors portée ou déchargée ?")
        log("EN : Is the ring out of range or discharged?")
    finally:
        disconnect_s = await disconnect(client, "INFO")
        reset_s = await restart_bt("fin INFO")

    cycle_s = time.perf_counter() - cycle_start
    if result is not None:
        result["disconnect_s"] = disconnect_s
        result["reset_s"] = reset_s
        result["cycle_s"] = cycle_s

    return result


async def measure(kind, label):
    client = None
    samples = []
    error = None
    done = asyncio.Event()
    start_sent = False
    stop_sent = False

    cycle_start = time.perf_counter()
    connect_s = None
    first_value_s = None
    samples_window_s = None
    measurement_s = None
    disconnect_s = None
    reset_s = None

    measure_start = None
    first_value_clock = None
    last_value_clock = None

    log(f"\n=== {label} ===")

    def notify(_sender, data):
        nonlocal error, first_value_s, first_value_clock, last_value_clock

        raw = bytes(data)
        log_raw(f"{label} | RX RAW | {hx(raw)}")

        if len(raw) != 16 or raw[0] != CMD_START or raw[1] != kind:
            return

        err = raw[2]
        value = raw[3]
        log_raw(f"{label} | DECODE | error={err} value={value}")

        if err != 0:
            error = err
            log(f"{label} | MEASUREMENT ERROR | code={err}")
            done.set()
            return

        if value != 0:
            now = time.perf_counter()
            if first_value_clock is None:
                first_value_clock = now
                if measure_start is not None:
                    first_value_s = now - measure_start
                log(f"{label} | FIRST VALUE after {fmt_s(first_value_s)}")

            last_value_clock = now
            samples.append(value)
            log(f"{label} | SAMPLE #{len(samples)} = {value}")

            if len(samples) >= TARGET_SAMPLES:
                done.set()

    try:
        client, connect_s = await connect(label)
        await client.start_notify(TX, notify)
        await asyncio.sleep(0.5)

        p_start = start_packet(kind)
        log_raw(f"{label} | TX START | {hx(p_start)}")
        log(f"{label} | START")

        measure_start = time.perf_counter()
        await client.write_gatt_char(RX, p_start, response=False)
        start_sent = True

        try:
            await asyncio.wait_for(done.wait(), MEASURE_TIMEOUT)
        except asyncio.TimeoutError:
            log(f"{label} | TIMEOUT {MEASURE_TIMEOUT}s")

        measurement_s = time.perf_counter() - measure_start

        if first_value_clock is not None and last_value_clock is not None:
            samples_window_s = last_value_clock - first_value_clock

        p_stop = stop_packet(kind)
        log_raw(f"{label} | TX STOP | {hx(p_stop)}")
        await client.write_gatt_char(RX, p_stop, response=False)
        stop_sent = True
        log(f"{label} | STOP SENT")

        # Laisse une seconde dans le log pour détecter d'éventuels paquets tardifs.
        await asyncio.sleep(1)

        log(f"{label} | SAMPLES={samples}")
        log(
            f"{label} | TIMES | connect={fmt_s(connect_s)} | "
            f"first={fmt_s(first_value_s)} | samples={fmt_s(samples_window_s)} | "
            f"measure={fmt_s(measurement_s)}"
        )

        if not samples or error is not None:
            if kind == HR:
                log("FR : La bague est-elle portée ?")
                log("EN : Is the ring being worn?")
            else:
                log("FR : La bague est-elle portée au doigt ?")
                log("EN : Is the ring being worn on a finger?")

    except (BleakDeviceNotFoundError, asyncio.TimeoutError) as e:
        log(f"{label} | DEVICE NOT AVAILABLE | {type(e).__name__}: {e}")
        log("FR : La bague est-elle hors portée ou déchargée ?")
        log("EN : Is the ring out of range or discharged?")
    except Exception as e:
        log(f"{label} | ERROR | {type(e).__name__}: {e}")
    finally:
        # Une seule tentative de STOP de sécurité. Aucun retry.
        if client and client.is_connected and start_sent and not stop_sent:
            try:
                p_stop = stop_packet(kind)
                log_raw(f"{label} | SAFETY TX STOP | {hx(p_stop)}")
                await client.write_gatt_char(RX, p_stop, response=False)
                log(f"{label} | SAFETY STOP SENT")
                await asyncio.sleep(0.5)
            except Exception as e:
                log(f"{label} | SAFETY STOP ERROR | {e}")

        disconnect_s = await disconnect(client, label)
        reset_s = await restart_bt(f"fin {label}")

    cycle_s = time.perf_counter() - cycle_start

    return {
        "samples": samples,
        "error": error,
        "ok": bool(samples) and error is None,
        "connect_s": connect_s,
        "first_value_s": first_value_s,
        "samples_window_s": samples_window_s,
        "measurement_s": measurement_s,
        "disconnect_s": disconnect_s,
        "reset_s": reset_s,
        "cycle_s": cycle_s,
    }


def mqtt_publish(payload):
    """Publication MQTT du résumé. Une erreur MQTT ne bloque jamais le test BLE."""
    client = None
    try:
        client = mqtt.Client()
        client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=15)
        client.loop_start()

        message = json.dumps(payload, ensure_ascii=False)
        info = client.publish(MQTT_TOPIC, message, qos=1, retain=True)
        info.wait_for_publish(timeout=5)

        log(f"MQTT | OK | {MQTT_TOPIC} | {message}")

    except Exception as e:
        log(f"MQTT | ERROR | {type(e).__name__}: {e}")

    finally:
        if client is not None:
            try:
                client.loop_stop()
                client.disconnect()
            except Exception:
                pass


async def main():
    program_start = time.perf_counter()

    log("=" * 70)
    log("WISS / COLMI SIMPLE - TEST 03 FAST")
    log(f"TARGET : {NAME} | {MAC}")
    log(f"LOG    : {LOGFILE}")
    log("INFO -> HR test portee -> [si portee] SpO2")
    log("SORTIES RAPIDES : NOT_AVAILABLE / ACCESSIBLE_NON_PORTEE")
    log("RAW BLE : fichier log uniquement")
    log("=" * 70)

    # 1) INFO + BATTERIE = test de joignabilite actuel, conserve tel quel.
    info = await info_battery()
    if info is None:
        total_s = time.perf_counter() - program_start
        log("TEST END | INFO unavailable -> NOT_AVAILABLE")
        log(f"PROGRAM TOTAL : {total_s:.3f}s")

        mqtt_publish({
            "time": datetime.now().astimezone().isoformat(timespec="seconds"),
            "device": NAME,
            "mac": MAC,
            "status": "NOT_AVAILABLE",
            "battery": None,
            "charging": None,
            "hr": [],
            "hr_error": None,
            "spo2": [],
            "spo2_error": None,
            "program_s": round(total_s, 3)
        })
        return

    # 2) HR en premier : sert aussi de test rapide "bague portee ?".
    hr = await measure(HR, "HEART_RATE")

    # Une erreur explicite de mesure HR signifie ici : joignable mais non portee.
    # On sort immediatement : inutile de lancer SpO2.
    if hr["error"] is not None:
        total_s = time.perf_counter() - program_start
        log("\n=== SORTIE RAPIDE / FAST EXIT ===")
        log("STATUS   : ACCESSIBLE_NON_PORTEE")
        log(f"BATTERY  : {info['level']}%")
        log(f"HR       : {hr['samples']} | error={hr['error']}")
        log("SpO2     : NON TESTE / NOT TESTED")
        log(f"TOTAL PROGRAMME : {total_s:.3f} s")

        mqtt_publish({
            "time": datetime.now().astimezone().isoformat(timespec="seconds"),
            "device": NAME,
            "mac": MAC,
            "status": "ACCESSIBLE_NON_PORTEE",
            "battery": info["level"],
            "charging": info["charging"],
            "hr": hr["samples"],
            "hr_error": hr["error"],
            "spo2": [],
            "spo2_error": None,
            "program_s": round(total_s, 3)
        })
        return

    # Si HR n'a ni valeur ni erreur explicite, on ne conclut PAS "non portee".
    # C'est un probleme/timeout de mesure distinct.
    if not hr["ok"]:
        total_s = time.perf_counter() - program_start
        log("\n=== SORTIE RAPIDE / FAST EXIT ===")
        log("STATUS   : MEASUREMENT_FAILED")
        log("HR n'a retourne ni mesure valide ni erreur explicite.")
        log(f"TOTAL PROGRAMME : {total_s:.3f} s")

        mqtt_publish({
            "time": datetime.now().astimezone().isoformat(timespec="seconds"),
            "device": NAME,
            "mac": MAC,
            "status": "MEASUREMENT_FAILED",
            "battery": info["level"],
            "charging": info["charging"],
            "hr": hr["samples"],
            "hr_error": hr["error"],
            "spo2": [],
            "spo2_error": None,
            "program_s": round(total_s, 3)
        })
        return

    # 3) HR valide => bague consideree portee : on mesure SpO2.
    spo2 = await measure(SPO2, "SPO2")
    total_s = time.perf_counter() - program_start

    log("\n=== RESULTAT FINAL / FINAL RESULT ===")
    log(f"HW       : {info['hw']}")
    log(f"FW       : {info['fw']}")
    log(f"BATTERY  : {info['level']}%")
    log(f"CHARGING : {info['charging']}")
    log("")
    log(f"HR       : {hr['samples']}" + ("" if hr["ok"] else f" | error={hr['error']}"))
    log(f"SpO2     : {spo2['samples']}" + ("" if spo2["ok"] else f" | error={spo2['error']}"))
    log("")
    log("--- TEMPS / TIMINGS ---")
    log(
        f"INFO  | connect={fmt_s(info['connect_s'])} | read={fmt_s(info['read_s'])} | "
        f"cycle complet={fmt_s(info['cycle_s'])}"
    )
    log(
        f"HR    | connect={fmt_s(hr['connect_s'])} | 1ere valeur={fmt_s(hr['first_value_s'])} | "
        f"6 samples={fmt_s(hr['samples_window_s'])} | mesure={fmt_s(hr['measurement_s'])} | "
        f"cycle complet={fmt_s(hr['cycle_s'])}"
    )
    log(
        f"SpO2  | connect={fmt_s(spo2['connect_s'])} | 1ere valeur={fmt_s(spo2['first_value_s'])} | "
        f"6 samples={fmt_s(spo2['samples_window_s'])} | mesure={fmt_s(spo2['measurement_s'])} | "
        f"cycle complet={fmt_s(spo2['cycle_s'])}"
    )
    log(f"TOTAL PROGRAMME : {total_s:.3f} s")
    log(f"LOG FILE        : {LOGFILE}")

    if spo2["ok"]:
        status = "ACCESSIBLE_PORTEE"
    elif spo2["error"] is not None:
        # HR etait valide, mais SpO2 renvoie une erreur : ne pas reclasser
        # automatiquement en "non portee" sans preuve supplementaire.
        status = "MEASUREMENT_ERROR"
    else:
        status = "MEASUREMENT_FAILED"

    mqtt_publish({
        "time": datetime.now().astimezone().isoformat(timespec="seconds"),
        "device": NAME,
        "mac": MAC,
        "status": status,
        "battery": info["level"],
        "charging": info["charging"],
        "hr": hr["samples"],
        "hr_error": hr["error"],
        "spo2": spo2["samples"],
        "spo2_error": spo2["error"],
        "program_s": round(total_s, 3)
    })


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nCtrl+C")
    finally:
        # Filet de sécurité final demandé pour WISS.
        subprocess.run(["systemctl", "restart", "bluetooth"], check=False)
