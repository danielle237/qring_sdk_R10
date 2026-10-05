#!/usr/bin/env python3
# WISS / COLMI SIMPLE - TEST 02
# - INFO/BATTERY, HR et SpO2 en transactions séparées
# - restart bluetooth après chaque transaction
# - RAW BLE dans le fichier log uniquement
# - temps détaillés dans le résultat final

import argparse
import asyncio
import os
import socket
import statistics
import subprocess
import uuid
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
# Paramètres lus dans un .env (le même que la GATEWAY RHM), sinon valeurs ci-dessus :
#   RING_MAC, RING_NAME, GATEWAY_NAME, MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASS, MQTT_PREFIX (eis/colmi)
# Fichier cherché : $WISS_ENV_FILE, .env à côté de ce script, /root/gateway_rhm/.env
def _load_env():
    for path in (os.getenv("WISS_ENV_FILE"), os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
                 "/root/gateway_rhm/.env"):
        if path and os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k.strip(), v.split(" #")[0].strip().strip('"').strip("'"))
            return path
    return None


ENV_FILE = _load_env()
MAC = os.getenv("RING_MAC") or MAC
NAME = os.getenv("RING_NAME") or NAME
MQTT_HOST = os.getenv("MQTT_HOST") or MQTT_HOST
MQTT_PORT = int(os.getenv("MQTT_PORT") or MQTT_PORT)
MQTT_USER = os.getenv("MQTT_USER") or MQTT_USER
MQTT_PASSWORD = os.getenv("MQTT_PASS") or os.getenv("MQTT_PASSWORD") or MQTT_PASSWORD
MQTT_PREFIX = (os.getenv("MQTT_PREFIX") or "eis/colmi").strip("/")

# Options (facultatives, valeurs par défaut = .env / comportement d'origine) :
#   --mac 30:32:42:32:64:01  --name "COLMI R10_6401"  --gateway <nom>  --json  --no-mqtt
# --json : dernière ligne « RESULT_JSON {...} » (même contenu que le message MQTT) lue par la GATEWAY RHM
# --no-mqtt : pas de publication MQTT par ce script (la GATEWAY RHM publie elle-même le résultat)
_ap = argparse.ArgumentParser(description="Mesure COLMI : batterie + HR + SpO2 en une connexion")
_ap.add_argument("--mac", default=MAC)
_ap.add_argument("--name", default=None)
_ap.add_argument("--gateway", default=os.getenv("GATEWAY_NAME") or socket.gethostname())
_ap.add_argument("--json", action="store_true")
_ap.add_argument("--no-mqtt", action="store_true")
_ap.add_argument("--req", default=None, help="reqId de la demande (app Client RHM / admin) : le résultat lui revient")
_ap.add_argument("--cmd", default="hr", choices=["hr", "spo2", "all"], help="mesure demandée par l'app")
_ap.add_argument("--live", action="store_true", help="début / fin de chaque mesure envoyés en direct (eis/colmi/<MAC>/…)")
ARGS = _ap.parse_args()
if ARGS.mac.upper() != MAC.upper():
    NAME = ARGS.name or ARGS.mac.upper()
MAC = ARGS.mac.upper()
NAME = ARGS.name or NAME

SCRIPT_DIR = Path(__file__).resolve().parent
LOGFILE = SCRIPT_DIR / f"wiss_test_04_{datetime.now():%Y%m%d_%H%M%S}.log"


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


class Live:
    """Début et fin de chaque mesure envoyés en direct sur eis/colmi/<MAC>/<mesure>, au format TV Android,
    avec le reqId de la demande : l'app qui a lancé la mesure reçoit son résultat dès qu'il est prêt."""

    def __init__(self):
        self.enabled = bool(ARGS.live or (ARGS.req and not ARGS.no_mqtt))
        self.req = ARGS.req or f"wiss-{uuid.uuid4().hex[:8]}"
        self.cmd = ARGS.cmd
        self.done = set()
        self.client = None
        if not self.enabled:
            return
        try:
            try:
                c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
            except AttributeError:
                c = mqtt.Client()
            if MQTT_USER:
                c.username_pw_set(MQTT_USER, MQTT_PASSWORD)
            c.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
            c.loop_start()
            self.client = c
        except Exception as e:
            log(f"LIVE | MQTT ERROR | {type(e).__name__}: {e}")

    def rid(self, sub):
        # la mesure demandée garde le reqId de l'app ; les autres valeurs de la même connexion : reqId-<mesure>
        return self.req if sub == self.cmd else f"{self.req}-{sub}"

    def send(self, sub, **fields):
        if not self.client:
            return
        msg = dict({"reqId": self.rid(sub), "type": sub, "source": "mqtt", "ringMac": MAC,
                    "gateway": ARGS.gateway, "ts": int(time.time())}, **fields)
        topic = f"{MQTT_PREFIX}/{MAC.replace(':', '').upper()}/{sub}"
        try:
            self.client.publish(topic, json.dumps(msg, ensure_ascii=False), qos=1).wait_for_publish(timeout=5)
            log(f"LIVE | {topic} | {fields.get('status')} {fields.get('value', fields.get('error', ''))}")
        except Exception as e:
            log(f"LIVE | ERROR | {type(e).__name__}: {e}")
        if fields.get("status") in ("ok", "error"):
            self.done.add(sub)

    def battery(self, level, charging):
        if level is not None:
            self.send("battery", status="ok", value=level, charging=bool(charging), unit="%")

    def start(self, kind):
        sub = "hr" if kind == HR else "spo2"
        if self.cmd == "all" and "all" not in self.done:
            self.send("all", status="measuring")
        self.send(sub, status="measuring")

    def end(self, kind, samples, error):
        sub, unit = ("hr", "bpm") if kind == HR else ("spo2", "%")
        if samples and error is None:
            self.send(sub, status="ok", value=round(statistics.median(samples)), values=list(samples), unit=unit)
        elif error is not None and kind == HR:
            self.send(sub, status="error", error="ring_removed")      # la bague n'est pas portée
        else:
            self.send(sub, status="error", error="measure_failed")

    def finish(self, hr, spo2):
        if self.cmd == "all":
            vals = {k: round(statistics.median(v)) for k, v in (("hr", hr), ("spo2", spo2)) if v}
            if vals:
                self.send("all", status="ok", **vals)
        self.fail("measure_failed")    # ce qui n'a pas abouti

    def fail(self, error):
        """Fin anticipée : la mesure demandée (et « all ») reçoivent une réponse."""
        for sub in (self.cmd, "all" if self.cmd == "all" else None):
            if sub and sub not in self.done:
                self.send(sub, status="error", error=error)

    def close(self):
        if self.client:
            try:
                self.client.loop_stop()
                self.client.disconnect()
            except Exception:
                pass


LIVE = None


def standard_messages(payload):
    """Résultat au même format que la TV Android / la GATEWAY RHM, sur eis/colmi/<MAC>/<mesure> :
    l'admin, le Client RHM et la base se mettent à jour comme pour une mesure de la TV."""
    req = f"wiss-{uuid.uuid4().hex[:8]}"
    base = {"reqId": req, "source": "mqtt", "ringMac": MAC, "gateway": ARGS.gateway, "ts": int(time.time())}
    st = payload.get("status")
    out = []
    if payload.get("battery") is not None:
        out.append(("battery", dict(base, type="battery", status="ok", value=payload["battery"],
                                    charging=bool(payload.get("charging")), unit="%")))
    hr, spo2 = payload.get("hr") or [], payload.get("spo2") or []
    if st == "ACCESSIBLE_PORTEE":
        if hr:
            out.append(("hr", dict(base, type="hr", status="ok", value=round(statistics.median(hr)), values=hr, unit="bpm")))
        if spo2:
            out.append(("spo2", dict(base, type="spo2", status="ok", value=round(statistics.median(spo2)), values=spo2, unit="%")))
    elif st == "ACCESSIBLE_NON_PORTEE":
        out.append(("hr", dict(base, type="hr", status="error", error="ring_removed")))
    elif st == "NOT_AVAILABLE":
        out.append(("hr", dict(base, type="hr", status="error", error="ring_disconnected")))
    else:
        out.append(("hr", dict(base, type="hr", status="error", error="measure_failed")))
    mac12 = MAC.replace(":", "").upper()
    return [(f"{MQTT_PREFIX}/{mac12}/{sub}", p) for sub, p in out]


def mqtt_publish(payload):
    """Publication MQTT du résumé. Une erreur MQTT ne bloque jamais le test BLE."""
    if ARGS.gateway:
        payload = dict(payload, gateway=ARGS.gateway)
    payload = dict(payload, live=bool(LIVE and LIVE.client))
    if ARGS.json:
        print("RESULT_JSON " + json.dumps(payload, ensure_ascii=False), flush=True)
    if ARGS.no_mqtt:
        log("MQTT | désactivé (--no-mqtt) : résultat publié par la GATEWAY RHM")
        return
    client = None
    try:
        try:
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        except AttributeError:          # paho-mqtt < 2.0
            client = mqtt.Client()
        client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=15)
        client.loop_start()

        message = json.dumps(payload, ensure_ascii=False)
        info = client.publish(MQTT_TOPIC, message, qos=1, retain=True)
        info.wait_for_publish(timeout=5)

        log(f"MQTT | OK | {MQTT_TOPIC} | {message}")

        # Mêmes valeurs sur les topics de la GATEWAY RHM (format TV Android) si elles n'ont pas été envoyées en direct
        for topic, msg in ([] if payload.get("live") else standard_messages(payload)):
            m = json.dumps(msg, ensure_ascii=False)
            client.publish(topic, m, qos=1).wait_for_publish(timeout=5)
            log(f"MQTT | OK | {topic} | {m}")

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
    """
    V4 FAST - expérimental
    Objectif: accélérer surtout le cas PORTEE en gardant UNE SEULE connexion BLE
    pour INFO/BATTERY -> HR -> SpO2.

    Les sorties rapides restent:
      - connexion impossible => NOT_AVAILABLE
      - HR error != 0 => ACCESSIBLE_NON_PORTEE
      - HR valide + SpO2 valide => ACCESSIBLE_PORTEE
    """
    global LIVE
    program_start = time.perf_counter()
    client = None
    LIVE = Live()

    log("=" * 70)
    log("WISS / COLMI SIMPLE - TEST 04 FAST - ONE CONNECTION")
    log(f"TARGET : {NAME} | {MAC}")
    if ARGS.gateway:
        log(f"GATEWAY: {ARGS.gateway}")
    log(f"LOG    : {LOGFILE}")
    log("ONE BLE CONNECTION : INFO/BATTERY -> HR -> SpO2")
    log("=" * 70)

    info = None
    hr = {"samples": [], "error": None, "ok": False}
    spo2 = {"samples": [], "error": None, "ok": False}

    try:
        # --------------------------------------------------------------
        # 1) UNE SEULE CONNEXION
        # --------------------------------------------------------------
        log("\n=== 1. CONNECT ===")
        try:
            client, connect_s = await connect("GATEWAY")
        except (BleakDeviceNotFoundError, asyncio.TimeoutError) as e:
            total_s = time.perf_counter() - program_start
            log(f"GATEWAY | NOT AVAILABLE | {type(e).__name__}: {e}")
            LIVE.fail("ring_disconnected")
            mqtt_publish({
                "time": datetime.now().astimezone().isoformat(timespec="seconds"),
                "device": NAME, "mac": MAC,
                "status": "NOT_AVAILABLE",
                "battery": None, "charging": None,
                "hr": [], "hr_error": None,
                "spo2": [], "spo2_error": None,
                "program_s": round(total_s, 3)
            })
            return
        except Exception as e:
            total_s = time.perf_counter() - program_start
            log(f"GATEWAY | NOT AVAILABLE | {type(e).__name__}: {e}")
            LIVE.fail("ring_disconnected")
            mqtt_publish({
                "time": datetime.now().astimezone().isoformat(timespec="seconds"),
                "device": NAME, "mac": MAC,
                "status": "NOT_AVAILABLE",
                "battery": None, "charging": None,
                "hr": [], "hr_error": None,
                "spo2": [], "spo2_error": None,
                "program_s": round(total_s, 3)
            })
            return

        # --------------------------------------------------------------
        # 2) INFO + BATTERY SUR LA MEME CONNEXION
        # --------------------------------------------------------------
        log("\n=== 2. INFO + BATTERY ===")
        info_start = time.perf_counter()

        hw = bytes(await client.read_gatt_char(HW)).decode(errors="replace").rstrip("\x00")
        fw = bytes(await client.read_gatt_char(FW)).decode(errors="replace").rstrip("\x00")
        log(f"INFO | HW={hw}")
        log(f"INFO | FW={fw}")

        battery_done = asyncio.Event()
        battery = {"level": None, "charging": None}

        def notify_battery(_sender, data):
            raw = bytes(data)
            log_raw(f"INFO | RX RAW | {hx(raw)}")
            if len(raw) == 16 and raw[0] == CMD_BATTERY:
                battery["level"] = raw[1]
                battery["charging"] = bool(raw[2])
                battery_done.set()

        await client.start_notify(TX, notify_battery)
        log_raw(f"INFO | TX BATTERY | {hx(BATTERY_PACKET)}")
        await client.write_gatt_char(RX, BATTERY_PACKET, response=False)

        try:
            await asyncio.wait_for(battery_done.wait(), 5)
        except asyncio.TimeoutError:
            log("INFO | BATTERY TIMEOUT")

        await client.stop_notify(TX)

        info_s = time.perf_counter() - info_start
        info = {
            "hw": hw,
            "fw": fw,
            "level": battery["level"],
            "charging": battery["charging"],
        }
        log(f"INFO | BATTERY={battery['level']}% | CHARGING={battery['charging']}")
        log(f"INFO | TIME={info_s:.3f}s")
        LIVE.battery(battery["level"], battery["charging"])

        # --------------------------------------------------------------
        # helper mesure sur la connexion déjà ouverte
        # --------------------------------------------------------------
        async def measure_same_connection(kind, label):
            samples = []
            error = None
            done = asyncio.Event()
            first_value_s = None
            first_clock = None
            last_clock = None
            measure_start = None

            def notify_measure(_sender, data):
                nonlocal error, first_value_s, first_clock, last_clock
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

                # Bloque exactement à TARGET_SAMPLES.
                if value != 0 and len(samples) < TARGET_SAMPLES:
                    now = time.perf_counter()
                    if first_clock is None:
                        first_clock = now
                        first_value_s = now - measure_start
                        log(f"{label} | FIRST VALUE after {fmt_s(first_value_s)}")
                    last_clock = now
                    samples.append(value)
                    log(f"{label} | SAMPLE #{len(samples)} = {value}")
                    if len(samples) >= TARGET_SAMPLES:
                        done.set()

            log(f"\n=== {label} ===")
            await client.start_notify(TX, notify_measure)
            await asyncio.sleep(0.25)

            p_start = start_packet(kind)
            log_raw(f"{label} | TX START | {hx(p_start)}")
            log(f"{label} | START")
            LIVE.start(kind)
            measure_start = time.perf_counter()
            await client.write_gatt_char(RX, p_start, response=False)

            try:
                await asyncio.wait_for(done.wait(), MEASURE_TIMEOUT)
            except asyncio.TimeoutError:
                log(f"{label} | TIMEOUT {MEASURE_TIMEOUT}s")

            measurement_s = time.perf_counter() - measure_start
            samples_window_s = None
            if first_clock is not None and last_clock is not None:
                samples_window_s = last_clock - first_clock

            # STOP avant de changer de mesure
            try:
                p_stop = stop_packet(kind)
                log_raw(f"{label} | TX STOP | {hx(p_stop)}")
                await client.write_gatt_char(RX, p_stop, response=False)
                log(f"{label} | STOP SENT")
                await asyncio.sleep(0.5)
            finally:
                try:
                    await client.stop_notify(TX)
                except Exception:
                    pass

            log(f"{label} | SAMPLES={samples}")
            log(
                f"{label} | TIMES | first={fmt_s(first_value_s)} | "
                f"samples={fmt_s(samples_window_s)} | measure={fmt_s(measurement_s)}"
            )

            LIVE.end(kind, samples, error)
            return {
                "samples": samples,
                "error": error,
                "ok": bool(samples) and error is None,
                "first_value_s": first_value_s,
                "samples_window_s": samples_window_s,
                "measurement_s": measurement_s,
            }

        # --------------------------------------------------------------
        # 3) HR = test rapide PORTEE / NON PORTEE
        # --------------------------------------------------------------
        hr = await measure_same_connection(HR, "HEART_RATE")

        if hr["error"] is not None:
            total_s = time.perf_counter() - program_start
            log("\n=== SORTIE RAPIDE ===")
            log("STATUS : ACCESSIBLE_NON_PORTEE")
            LIVE.fail("ring_removed")
            mqtt_publish({
                "time": datetime.now().astimezone().isoformat(timespec="seconds"),
                "device": NAME, "mac": MAC,
                "status": "ACCESSIBLE_NON_PORTEE",
                "battery": info["level"], "charging": info["charging"],
                "hr": hr["samples"], "hr_error": hr["error"],
                "spo2": [], "spo2_error": None,
                "program_s": round(total_s, 3)
            })
            return

        if not hr["ok"]:
            total_s = time.perf_counter() - program_start
            log("\n=== SORTIE RAPIDE ===")
            log("STATUS : MEASUREMENT_FAILED")
            LIVE.fail("measure_failed")
            mqtt_publish({
                "time": datetime.now().astimezone().isoformat(timespec="seconds"),
                "device": NAME, "mac": MAC,
                "status": "MEASUREMENT_FAILED",
                "battery": info["level"], "charging": info["charging"],
                "hr": hr["samples"], "hr_error": hr["error"],
                "spo2": [], "spo2_error": None,
                "program_s": round(total_s, 3)
            })
            return

        # --------------------------------------------------------------
        # 4) HR valide => portée => SpO2 sur LA MEME connexion
        # --------------------------------------------------------------
        spo2 = await measure_same_connection(SPO2, "SPO2")

        total_s = time.perf_counter() - program_start

        if spo2["ok"]:
            status = "ACCESSIBLE_PORTEE"
        elif spo2["error"] is not None:
            # HR valide prouve déjà que la bague était portée.
            status = "ACCESSIBLE_PORTEE"
        else:
            status = "MEASUREMENT_FAILED"

        log("\n=== RESULTAT FINAL / FINAL RESULT ===")
        log(f"HW       : {info['hw']}")
        log(f"FW       : {info['fw']}")
        log(f"BATTERY  : {info['level']}%")
        log(f"CHARGING : {info['charging']}")
        log(f"HR       : {hr['samples']} | error={hr['error']}")
        log(f"SpO2     : {spo2['samples']} | error={spo2['error']}")
        log(f"TOTAL PROGRAMME : {total_s:.3f} s")
        LIVE.finish(hr["samples"], spo2["samples"])

        mqtt_publish({
            "time": datetime.now().astimezone().isoformat(timespec="seconds"),
            "device": NAME, "mac": MAC,
            "status": status,
            "battery": info["level"], "charging": info["charging"],
            "hr": hr["samples"], "hr_error": hr["error"],
            "spo2": spo2["samples"], "spo2_error": spo2["error"],
            "program_s": round(total_s, 3)
        })

    except Exception as e:
        total_s = time.perf_counter() - program_start
        log(f"V4 | ERROR | {type(e).__name__}: {e}")
        LIVE.fail("measure_failed")
        mqtt_publish({
            "time": datetime.now().astimezone().isoformat(timespec="seconds"),
            "device": NAME, "mac": MAC,
            "status": "MEASUREMENT_FAILED" if client else "NOT_AVAILABLE",
            "battery": info["level"] if info else None,
            "charging": info["charging"] if info else None,
            "hr": hr.get("samples", []),
            "hr_error": hr.get("error"),
            "spo2": spo2.get("samples", []),
            "spo2_error": spo2.get("error"),
            "program_s": round(total_s, 3)
        })

    finally:
        # Une seule déconnexion et un seul restart BT en fin de cycle.
        if client is not None:
            await disconnect(client, "GATEWAY")
        await restart_bt("fin cycle V4")
        if LIVE:
            LIVE.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nCtrl+C")
    finally:
        # Filet de sécurité final demandé pour WISS.
        subprocess.run(["systemctl", "restart", "bluetooth"], check=False)
