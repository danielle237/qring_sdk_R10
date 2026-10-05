#!/usr/bin/env python3
"""
GATEWAY RHM — version Linux (Raspberry Pi / DietPi…) à la place de la TV Android.

Reçoit les commandes MQTT de l'admin et de Client RHM (même protocole que la TV),
lance `colmi_r02_client` pour parler à la bague en Bluetooth, et renvoie les résultats
dans le même format : l'admin, Client RHM et la base marchent sans changement.

  eis/colmi/<MAC>/cmd   {"cmd":"hr","reqId":"app-wissbra-p1a2b3c"}
      → colmi_r02_client --address <MAC> get-real-time heart-rate
      → eis/colmi/<MAC>/hr  {"status":"ok","value":69,"reqId":…}

Une seule commande Bluetooth à la fois (file d'attente). Réglages : fichier .env à côté du script.
"""
import json
import logging
import os
import queue
import re
import shutil
import socket
import statistics
import subprocess
import threading
import time
import uuid

import paho.mqtt.client as mqtt

# ============================================================================ réglages

def load_env(path):
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env(os.getenv("GATEWAY_ENV_FILE") or os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER", "")
MQTT_PASS = os.getenv("MQTT_PASS", "")
PREFIX = os.getenv("MQTT_PREFIX", "eis/colmi").strip("/")
RING_MAC = os.getenv("RING_MAC", "").upper()
GATEWAY = os.getenv("GATEWAY_NAME") or socket.gethostname()
CLI = os.getenv("COLMI_CLI") or shutil.which("colmi_r02_client") or os.path.expanduser("~/.local/bin/colmi_r02_client")
CMD_TIMEOUT = int(os.getenv("CMD_TIMEOUT", "90"))            # une mesure dure ~30 s
STATUS_EVERY = int(os.getenv("STATUS_SECONDS", "60"))       # statut publié (comme la TV)
CHECK_EVERY = int(os.getenv("RING_CHECK_SECONDS", "300"))   # « info » pour voir si la bague répond (0 = jamais)
VERSION = "linux-1.0"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gateway")

if not RING_MAC:
    raise SystemExit("RING_MAC manquant dans .env (ex. RING_MAC=30:32:42:32:64:01)")

MAC12 = RING_MAC.replace(":", "")
BASE = f"{PREFIX}/{MAC12}"
GW_BASE = f"{PREFIX}/gateway/{re.sub(r'[^A-Za-z0-9_.-]', '_', GATEWAY)}"

# Commandes MQTT → arguments de colmi_r02_client
REALTIME = {"hr": "heart-rate", "spo2": "spo2", "hrv": "hrv", "stress": "pressure"}
UNITS = {"hr": "bpm", "spo2": "%", "hrv": "ms", "stress": "score"}
UNSUPPORTED = {"temp", "bp", "sleep", "workouts", "history"}
# Sédentarité (calculée à partir des pas par tranche de 15 min) : journée 8 h → 21 h, < 30 pas = immobile
SED_START_H = int(os.getenv("SEDENTARY_START_HOUR", "8"))
SED_END_H = int(os.getenv("SEDENTARY_END_HOUR", "21"))
SED_MIN_STEPS = int(os.getenv("SEDENTARY_STEPS_PER_SLOT", "30"))

# ============================================================================ état

state = {
    "ring": "connecting",       # connected / disconnected / connecting
    "worn": None,
    "battery": None,
    "charging": False,
    "firmware": "",
    "lastOk": 0,
    "measuring": None,
}
lock = threading.Lock()
jobs = queue.Queue()
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"gateway-linux-{uuid.uuid4().hex[:6]}")


def now():
    return int(time.time())


def status_payload(online=True):
    with lock:
        return {
            "online": online, "ring": state["ring"] if online else "unknown",
            "ringMac": RING_MAC, "ringModel": "COLMI", "ringName": os.getenv("RING_NAME", ""),
            "firmware": state["firmware"], "battery": state["battery"], "charging": state["charging"],
            "worn": state["worn"], "measuring": state["measuring"],
            "gateway": GATEWAY, "deviceName": GATEWAY, "lanIp": lan_ip(),
            "appVersion": VERSION, "ts": now(),
        }


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return None


def publish_status():
    p = json.dumps(status_payload(True))
    client.publish(f"{BASE}/status", p, qos=1, retain=True)
    client.publish(f"{GW_BASE}/status", p, qos=1, retain=True)


def publish(sub, payload):
    payload.setdefault("ts", now())
    payload.setdefault("ringMac", RING_MAC)
    payload.setdefault("gateway", GATEWAY)
    client.publish(f"{BASE}/{sub}", json.dumps(payload), qos=1)


# ============================================================================ Bluetooth (colmi_r02_client)

def run_cli(*args):
    """(code, texte) — texte = sortie standard + erreurs."""
    cmd = [CLI, "--address", RING_MAC, *args]
    log.info("→ %s", " ".join(cmd[1:]))
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=CMD_TIMEOUT)
        out = (r.stdout or "") + (r.stderr or "")
        log.info("← %s", out.strip().replace("\n", " | ")[:300])
        return r.returncode, out
    except subprocess.TimeoutExpired:
        return -1, "timeout"
    except FileNotFoundError:
        return -2, f"colmi_r02_client introuvable ({CLI})"


def parse_values(out):
    """« [70, 69, 69, 68] » → [70, 69, 69, 68] (valeurs > 0 seulement)."""
    m = re.findall(r"\[([0-9,\s.]+)\]", out)
    if not m:
        return []
    return [float(x) for x in m[-1].split(",") if x.strip() and float(x) > 0]


def error_code(out, code):
    t = out.lower()
    if "worn" in t or "no heart rate" in t or "no data" in t:
        return "ring_removed"
    if code == -1 or "timeout" in t:
        return "timeout"
    if any(w in t for w in ("not found", "failed to connect", "no device", "bleak", "disconnected", "could not")):
        return "ring_disconnected"
    return "measure_failed"


def set_ring(ok, worn=None):
    with lock:
        if ok:
            state["ring"], state["lastOk"] = "connected", now()
        else:
            state["ring"] = "disconnected"
        if worn is not None:
            state["worn"] = worn


def measure(key):
    """(valeur, liste, erreur) pour hr / spo2 / hrv / stress."""
    code, out = run_cli("get-real-time", REALTIME[key])
    vals = parse_values(out)
    if vals:
        value = round(statistics.median(vals))
        set_ring(True, worn=True)
        return value, vals, None
    err = error_code(out, code)
    set_ring(err in ("ring_removed", "measure_failed"), worn=False if err == "ring_removed" else None)
    return None, [], err


def read_info():
    """Batterie + firmware avec « info ». True si la bague a répondu."""
    # device info {'hw_version': 'RT03CR_V1.0', 'fw_version': 'RT03CR_1.00.01_250104'}
    # battery: BatteryInfo(battery_level=83, charging=False)
    code, out = run_cli("info")
    m = re.search(r"battery_level\s*=\s*(\d{1,3})", out) or re.search(r"batter[a-z_ ]*[^0-9]{0,20}(\d{1,3})", out, re.I)
    fw = re.search(r"fw_version'?\s*[:=]\s*'?([A-Za-z0-9_.\-]+)", out) or \
        re.search(r"(?:firmware|fw)[a-z_ ]*[^A-Za-z0-9]{0,5}([A-Za-z0-9_.]+)", out, re.I)
    ch = re.search(r"charging\s*=\s*(True|False)", out)
    if code == 0 and (m or fw):
        with lock:
            if m:
                state["battery"] = int(m.group(1))
            if fw:
                state["firmware"] = fw.group(1)
            if ch:
                state["charging"] = ch.group(1) == "True"
        set_ring(True)
        return True
    set_ring(False)
    return False


def read_steps():
    """« get-steps » : tableau par tranche de 15 min (time_index 0…95) → {index: (pas, distance m, calories brutes)}.
    None si la bague n'a pas répondu."""
    code, out = run_cli("get-steps")
    slots = {}
    for line in out.splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) == 7 and all(p.isdigit() for p in parts):
            _, _, _, idx, cal, steps, dist = (int(p) for p in parts)
            old = slots.get(idx, (0, 0, 0))
            slots[idx] = (old[0] + steps, old[1] + dist, old[2] + cal)
    if code != 0 and not slots:
        set_ring(False)
        return None
    set_ring(True)
    return slots


def sedentary_from(slots):
    """Tranches de 15 min entre SED_START_H et maintenant (max SED_END_H) avec moins de SED_MIN_STEPS pas."""
    lt = time.localtime()
    cur = (lt.tm_hour * 60 + lt.tm_min) // 15
    first, last = SED_START_H * 4, min(cur, SED_END_H * 4)
    still, best, best_start, run, run_start = 0, 0, None, 0, None
    for i in range(first, last):
        if slots.get(i, (0, 0, 0))[0] < SED_MIN_STEPS:
            still += 1
            if run == 0:
                run_start = i
            run += 1
            if run > best:
                best, best_start = run, run_start
        else:
            run = 0
    hm = lambda i: f"{i // 4:02d}:{(i % 4) * 15:02d}"
    return {
        "stillMinutes": still * 15, "sedentaryMinutes": 0,       # même champs que la TV (carte « Sédentarité »)
        "longestMinutes": best * 15,
        "longestFrom": hm(best_start) if best_start is not None else None,
        "longestTo": hm(best_start + best) if best_start is not None else None,
        "fromHour": SED_START_H, "toHour": SED_END_H, "method": "steps_15min",
    }


# ============================================================================ commandes

def handle(cmd, req):
    base = {"reqId": req, "source": "mqtt"}
    if cmd == "info-silent":
        # Contrôle périodique : batterie + bague joignable, sans publier de résultat
        read_info()
        publish_status()
        return
    if cmd in REALTIME:
        started = now()
        with lock:
            state["measuring"] = cmd
        publish(cmd, dict(base, status="measuring"))
        publish_status()
        value, vals, err = measure(cmd)
        with lock:
            state["measuring"] = None
        if err:
            publish(cmd, dict(base, status="error", error=err))
        else:
            publish(cmd, dict(base, status="ok", value=value, values=vals, unit=UNITS[cmd], _dur=now() - started))
        publish_status()
    elif cmd == "all":
        with lock:
            state["measuring"] = "all"
        publish("all", dict(base, status="measuring"))
        res, err = {}, None
        for k in ("hr", "spo2", "hrv", "stress"):
            value, _, e = measure(k)
            if e == "ring_removed" or e == "ring_disconnected":
                err = e
                break
            if value is not None:
                res[k] = value
        with lock:
            state["measuring"] = None
        if res:
            publish("all", dict(base, status="ok", **res))
        else:
            publish("all", dict(base, status="error", error=err or "measure_failed"))
        publish_status()
    elif cmd in ("battery", "info"):
        if read_info():
            with lock:
                b = state["battery"]
            if cmd == "battery" and b is not None:
                publish("battery", dict(base, status="ok", value=b, charging=state["charging"], unit="%"))
            elif cmd == "info":
                publish("info", dict(base, status="ok", firmware=state["firmware"], battery=b))
            else:
                publish(cmd, dict(base, status="error", error="no_data"))
        else:
            publish(cmd, dict(base, status="error", error="ring_disconnected"))
        publish_status()
    elif cmd in ("steps", "sedentary"):
        slots = read_steps()
        if slots is None:
            publish(cmd, dict(base, status="error", error="ring_disconnected"))
        elif cmd == "steps":
            hourly = [0] * 24
            for i, (st, _, _) in slots.items():
                hourly[min(i // 4, 23)] += st
            publish("steps", dict(base, status="ok", day=0,
                                  steps=sum(v[0] for v in slots.values()),
                                  distance=sum(v[1] for v in slots.values()),     # mètres
                                  calories=sum(v[2] for v in slots.values()),     # brutes (÷ 1000 = kcal)
                                  hourly=hourly))
        else:
            publish("sedentary", dict(base, status="ok", day=0, **sedentary_from(slots)))
        publish_status()
    elif cmd == "ping":
        publish("ping", dict(base, status="ok"))
    elif cmd in UNSUPPORTED:
        publish(cmd, dict(base, status="error", error="not_supported"))
    else:
        publish("cmd", dict(base, status="error", error="unknown_command", cmd=cmd))


def worker():
    while True:
        cmd, req = jobs.get()
        try:
            handle(cmd, req)
        except Exception:
            log.exception("commande %s", cmd)
            publish(cmd, {"reqId": req, "status": "error", "error": "measure_failed"})


# ============================================================================ MQTT

def on_connect(c, userdata, flags, reason_code, properties=None):
    log.info("Connecté au broker %s:%s (%s)", MQTT_HOST, MQTT_PORT, reason_code)
    c.subscribe(f"{BASE}/cmd", qos=1)
    c.subscribe(f"{GW_BASE}/cmd", qos=1)
    publish_status()


def on_message(c, userdata, msg):
    try:
        p = json.loads(msg.payload.decode("utf-8") or "{}")
    except ValueError:
        return
    cmd = str(p.get("cmd") or "").lower()
    if not cmd:
        return
    req = p.get("reqId") or f"lx-{uuid.uuid4().hex[:8]}"
    log.info("Commande reçue : %s (%s)", cmd, req)
    if cmd == "cancel":
        return  # la mesure en cours finit d'elle-même (~30 s)
    jobs.put((cmd, req))


def main():
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS)
    # Gateway coupée : message de dernière volonté (la bague garde son dernier état côté serveur)
    client.will_set(f"{GW_BASE}/status", json.dumps({"online": False, "gateway": GATEWAY, "ts": now()}), qos=1, retain=True)
    client.on_connect = on_connect
    client.on_message = on_message
    client.reconnect_delay_set(1, 30)
    client.connect_async(MQTT_HOST, MQTT_PORT, keepalive=30)
    client.loop_start()
    threading.Thread(target=worker, daemon=True).start()
    log.info("GATEWAY RHM Linux « %s » · bague %s · %s", GATEWAY, RING_MAC, CLI)

    last_check = 0
    while True:
        time.sleep(STATUS_EVERY)
        # Bague joignable ? « info » de temps en temps, seulement si rien n'est en cours
        if CHECK_EVERY and now() - last_check >= CHECK_EVERY and jobs.empty() and state["measuring"] is None:
            last_check = now()
            jobs.put(("info-silent", None))
        if client.is_connected():
            publish_status()


if __name__ == "__main__":
    main()
