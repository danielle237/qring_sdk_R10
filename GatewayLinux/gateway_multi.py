#!/usr/bin/env python3
"""
GATEWAY RHM Linux — mode MULTI-BAGUES (zones). Remplace « python3 gateway_linux.py » dans le service.

  * Liste des bagues de cette gateway : envoyée par l'admin (zones principale / secondaires), retenue sur
      eis/colmi/gateway/<nom>/rings   {"rings": [{"mac": "30:32:42:32:64:01", "role": "main"}, …]}
    (sans liste reçue : RING_MAC du .env, comme avant)
  * Une instance de gateway_linux.py par bague (mesures, statut de la bague : inchangé)
  * Écoute passive en continu (scan_rings.py) : présence + RSSI de toutes les bagues, publiée sur
      eis/colmi/gateway/<nom>/presence  {"ts", "rings": [{"mac","role"}], "seen": {mac: {"rssi","n"}}}
    → client_api localise chaque bague en temps réel (meilleur RSSI, zone principale favorisée)
  * Un seul Bluetooth : verrou partagé (une mesure à la fois ; l'écoute se met en pause pendant une mesure)
  * Statut de la gateway (admin) + redémarrage Bluetooth / service / machine depuis l'admin

Réglages : le même .env que gateway_linux.py (GATEWAY_NAME, MQTT_*, …) + facultatifs :
  SCAN_PYTHON=python3.14          (Python avec bleak ; par défaut python3.14, comme tes scripts)
  SCAN_WINDOW=4    SCAN_PAUSE=1    GATEWAY_RUN_DIR=/run/gateway-rhm
"""
import json
import logging
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
import fcntl

import paho.mqtt.client as mqtt

HERE = os.path.dirname(os.path.abspath(__file__))


def load_env(path):
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


ENV_FILE = os.getenv("GATEWAY_ENV_FILE") or os.path.join(HERE, ".env")
load_env(ENV_FILE)


def norm_mac(v):
    h = re.sub(r"[^0-9A-Fa-f]", "", str(v or ""))
    if len(h) != 12 or h in ("000000000000", "FFFFFFFFFFFF"):
        return ""
    return ":".join(h[i:i + 2] for i in range(0, 12, 2)).upper()


MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER", "")
MQTT_PASS = os.getenv("MQTT_PASS", "")
PREFIX = os.getenv("MQTT_PREFIX", "eis/colmi").strip("/")
GATEWAY = os.getenv("GATEWAY_NAME") or socket.gethostname()
GATEWAY_TYPE = (os.getenv("GATEWAY_TYPE") or "linux").strip().lower()
GW_BASE = f"{PREFIX}/gateway/{re.sub(r'[^A-Za-z0-9_.-]', '_', GATEWAY)}"
VERSION = "linux-3.2-multi"
RUN_DIR = os.getenv("GATEWAY_RUN_DIR", "/run/gateway-rhm")
CHILD = os.getenv("CHILD_SCRIPT") or os.path.join(HERE, "gateway_linux.py")
# Écoute passive (scan_rings.py) : désactivée par défaut. Présence / hors portée = test_reachable_v1.py,
# demandé par client_api à tour de rôle aux Pi des zones de la bague.
PASSIVE_SCAN = os.getenv("PASSIVE_SCAN", "0").lower() in ("1", "true", "yes")
SCAN_SCRIPT = os.getenv("SCAN_SCRIPT") or os.path.join(HERE, "scan_rings.py")
# Python de l'écoute passive (doit avoir bleak) : SCAN_PYTHON, sinon python3.14 (comme test_reachable_v1.py)
SCAN_PYTHON = (shutil.which(os.getenv("SCAN_PYTHON") or "") or os.getenv("SCAN_PYTHON")
               or shutil.which("python3.14") or sys.executable)
SCAN_WINDOW = float(os.getenv("SCAN_WINDOW", "4"))
SCAN_PAUSE = float(os.getenv("SCAN_PAUSE", "1"))
STATUS_EVERY = int(os.getenv("STATUS_SECONDS", "60"))
WAN_URL = os.getenv("WAN_IP_URL", "https://api.ipify.org")
SERVICE_NAME = os.getenv("SERVICE_NAME", "gateway-rhm")
ALLOW_RESTART = os.getenv("ALLOW_REMOTE_RESTART", "1") != "0"
ALLOW_REBOOT = os.getenv("ALLOW_REMOTE_REBOOT", "1") != "0"
ALLOW_BT_RESTART = os.getenv("ALLOW_REMOTE_BT_RESTART", "1") != "0"
FALLBACK_MAC = norm_mac(os.getenv("RING_MAC", ""))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [multi] %(message)s")
log = logging.getLogger("multi")

lock = threading.Lock()
child_lock = threading.Lock()
rings = {}            # mac → role ("main" / "secondary")
rings_received = {"ok": False}
children = {}         # mac → {"p": Popen, "started": ts, "stop": bool}
scan = {"p": None, "lastTs": 0, "errors": 0, "lastErr": None}
seen = {}             # mac → {"rssi", "max", "n", "ts", "name"}
busy = {"v": None}
wan = {"ip": None, "ts": 0}
stopping = {"v": False}
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"gateway-multi-{uuid.uuid4().hex[:6]}")


def now():
    return int(time.time())


# ---------------------------------------------------------------------------- infos machine (comme gateway_linux.py)
def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return None


def wan_ip(force=False):
    if not force and wan["ip"] and now() - wan["ts"] < 1800:
        return wan["ip"]
    try:
        with urllib.request.urlopen(WAN_URL, timeout=5) as r:
            ip = r.read(64).decode("ascii", "ignore").strip()
        if re.fullmatch(r"[0-9a-fA-F:.]{3,45}", ip):
            wan["ip"] = ip
    except Exception:
        pass
    wan["ts"] = now()
    return wan["ip"]


def sys_info():
    out = {}
    try:
        load1 = os.getloadavg()[0]
        out["cpu"] = round(min(100.0, load1 / (os.cpu_count() or 1) * 100), 0)
        out["load"] = round(load1, 2)
    except OSError:
        pass
    try:
        mem = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                mem[k] = int(v.split()[0])
        total, avail = mem.get("MemTotal", 0), mem.get("MemAvailable", 0)
        if total:
            out.update(ramUsedMb=round((total - avail) / 1024), ramTotalMb=round(total / 1024),
                       ram=round((total - avail) * 100 / total))
    except (OSError, ValueError):
        pass
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            out["tempC"] = round(int(f.read().strip()) / 1000, 1)
    except (OSError, ValueError):
        pass
    try:
        du = shutil.disk_usage("/")
        out["disk"] = round(du.used * 100 / du.total)
    except OSError:
        pass
    try:
        with open("/proc/uptime") as f:
            out["uptime"] = int(float(f.read().split()[0]))
    except (OSError, ValueError):
        pass
    return out


# ---------------------------------------------------------------------------- statut de la gateway
def read_busy():
    """Mesure en cours sur le boîtier (fichier écrit par l'instance qui tient le Bluetooth)."""
    try:
        with open(os.path.join(RUN_DIR, "busy.json")) as f:
            b = json.load(f)
        os.kill(int(b.get("pid") or 0), 0)    # instance encore vivante ?
        return {"mac": b.get("mac"), "cmd": b.get("cmd"), "reqId": b.get("reqId"), "since": b.get("ts")}
    except (OSError, ValueError, TypeError):
        return None


def status_payload(online=True):
    with lock:
        macs = sorted(rings)
        roles = [{"mac": m, "role": rings[m]} for m in macs]
    return {
        "online": online, "gateway": GATEWAY, "deviceName": GATEWAY, "gatewayType": GATEWAY_TYPE,
        "appVersion": VERSION, "multi": True, "scanner": scan["p"] is not None and now() - scan["lastTs"] < 60,
        "rings": roles, "ringMac": macs[0] if len(macs) == 1 else "", "ring": "connected" if macs else "no_ring",
        "busy": busy["v"], "lanIp": lan_ip(), "wanIp": wan["ip"], "sys": sys_info(), "ts": now(),
    }


def publish_status():
    if client.is_connected():
        client.publish(f"{GW_BASE}/status", json.dumps(status_payload()), qos=1, retain=True)


# ---------------------------------------------------------------------------- instances par bague
def child_env(mac):
    env = dict(os.environ)
    env.update(RING_MAC=mac, GATEWAY_MULTI_CHILD="1", GATEWAY_RUN_DIR=RUN_DIR, LOG_TAG=mac[-5:],
               GATEWAY_ENV_FILE=ENV_FILE,
               RING_NAME=os.getenv("RING_NAME", "") if mac == FALLBACK_MAC else "")
    return env


def start_child(mac):
    p = subprocess.Popen([sys.executable, CHILD], env=child_env(mac), cwd=HERE)
    children[mac] = {"p": p, "started": now(), "stop": False}
    log.info("Bague %s (%s) : instance démarrée (pid %s)", mac, rings.get(mac), p.pid)


def stop_child(mac, why):
    c = children.pop(mac, None)
    if not c:
        return
    c["stop"] = True
    log.info("Bague %s : instance arrêtée (%s)", mac, why)
    try:
        c["p"].terminate()
        c["p"].wait(timeout=10)
    except Exception:
        try:
            c["p"].kill()
        except Exception:
            pass


def clean_wants():
    """Fichiers « want-* » d'une instance morte en attente du Bluetooth : sinon l'écoute resterait bloquée."""
    try:
        names = [n for n in os.listdir(RUN_DIR) if n.startswith("want-") and n != "want-gateway"]
    except OSError:
        return
    for n in names:
        path = os.path.join(RUN_DIR, n)
        try:
            with open(path) as f:
                pid = int((f.read() or "0").strip() or 0)
            os.kill(pid, 0)
        except (OSError, ValueError):
            try:
                os.remove(path)
            except OSError:
                pass


def sync_children():
    with child_lock:
        _sync_children()


def _sync_children():
    with lock:
        want = set(rings)
    for mac in list(children):
        if mac not in want:
            stop_child(mac, "plus dans les zones de cette gateway")
    for mac in sorted(want):
        c = children.get(mac)
        if c is None:
            start_child(mac)
        elif c["p"].poll() is not None:
            code = c["p"].returncode
            if code == 78:
                continue   # configuration invalide : pas de relance en boucle
            if now() - c["started"] >= 5:
                log.warning("Bague %s : instance arrêtée (code %s) → relance", mac, code)
                start_child(mac)
    write_macs()


def write_macs():
    with lock:
        macs = sorted(rings)
    os.makedirs(RUN_DIR, exist_ok=True)
    tmp = os.path.join(RUN_DIR, ".macs.txt")
    with open(tmp, "w") as f:
        f.write("\n".join(macs) + ("\n" if macs else ""))
    os.replace(tmp, os.path.join(RUN_DIR, "macs.txt"))


def set_rings(new, why):
    with lock:
        changed = new != rings
        rings.clear()
        rings.update(new)
    if changed:
        log.info("Bagues de cette gateway (%s) : %s", why,
                 ", ".join(f"{m} ({r})" for m, r in sorted(new.items())) or "aucune")
        sync_children()
        publish_status()


# ---------------------------------------------------------------------------- écoute passive
def write_seen():
    tmp = os.path.join(RUN_DIR, ".seen.json")
    with lock:
        data = {"scanTs": scan["lastTs"], "rings": {m: dict(v) for m, v in seen.items()}}
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, os.path.join(RUN_DIR, "seen.json"))


def scanner_loop():
    while not stopping["v"]:
        if not os.path.exists(SCAN_PYTHON) or not os.path.exists(SCAN_SCRIPT):
            log.error("Écoute passive impossible : %s ou %s introuvable (SCAN_PYTHON dans .env)", SCAN_PYTHON, SCAN_SCRIPT)
            time.sleep(60)
            continue
        args = [SCAN_PYTHON, SCAN_SCRIPT, "--run", RUN_DIR, "--macs-file", os.path.join(RUN_DIR, "macs.txt"),
                "--window", str(SCAN_WINDOW), "--pause", str(SCAN_PAUSE)]
        log.info("Écoute passive démarrée (fenêtres de %s s)", SCAN_WINDOW)
        p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        scan["p"] = p
        for line in p.stdout:
            line = line.strip()
            if not line.startswith("{"):
                if line:
                    log.debug("scan : %s", line)
                continue
            try:
                m = json.loads(line)
            except ValueError:
                continue
            if m.get("error"):
                scan["errors"] += 1
                if scan["errors"] in (1, 5) or scan["errors"] % 30 == 0:
                    log.warning("Écoute passive : %s", m["error"])
                continue
            scan["errors"] = 0
            on_window(m)
        scan["p"] = None
        if not stopping["v"]:
            log.warning("Écoute passive arrêtée (code %s) → relance dans 5 s", p.wait())
            time.sleep(5)


def on_window(m):
    t = int(m.get("ts") or now())
    with lock:
        for mac, v in (m.get("seen") or {}).items():
            if mac in rings:
                seen[mac] = dict(v, ts=t)
        scan["lastTs"] = t
        roles = [{"mac": x, "role": rings[x]} for x in sorted(rings)]
        out = {mac: {"rssi": v["rssi"], "max": v.get("max"), "n": v.get("n")}
               for mac, v in (m.get("seen") or {}).items() if mac in rings}
    write_seen()
    if client.is_connected() and roles:
        client.publish(f"{GW_BASE}/presence", json.dumps({
            "gateway": GATEWAY, "ts": t, "window": m.get("window"), "partial": bool(m.get("partial")),
            "rings": roles, "seen": out, "busy": busy["v"]}), qos=0)


# ---------------------------------------------------------------------------- commandes de l'admin
def bt_locked(fn):
    """Exécute fn en tenant le Bluetooth du boîtier (attend la mesure en cours)."""
    os.makedirs(RUN_DIR, exist_ok=True)
    want = os.path.join(RUN_DIR, "want-gateway")
    open(want, "w").close()
    f = open(os.path.join(RUN_DIR, "bt.lock"), "a+")
    try:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            os.remove(want)
        except OSError:
            pass
        return fn()
    finally:
        fcntl.flock(f, fcntl.LOCK_UN)
        f.close()
        try:
            os.remove(want)
        except OSError:
            pass


def bt_restart(req):
    ack = {"reqId": req, "gateway": GATEWAY}
    if not ALLOW_BT_RESTART:
        client.publish(f"{GW_BASE}/btrestart", json.dumps(dict(ack, status="error", error="not_allowed", ts=now())), qos=1)
        return
    client.publish(f"{GW_BASE}/btrestart", json.dumps(dict(ack, status="running", ts=now())), qos=1)

    def do():
        log.info("Redémarrage du service Bluetooth demandé depuis l'admin")
        subprocess.run(["systemctl", "restart", "bluetooth"], capture_output=True, timeout=30)
        time.sleep(2)
        subprocess.run(["bluetoothctl", "power", "on"], capture_output=True, timeout=10)
        time.sleep(1)
    try:
        bt_locked(do)
        time.sleep(SCAN_WINDOW + SCAN_PAUSE + 2)
        ok_ = not PASSIVE_SCAN or now() - scan["lastTs"] < SCAN_WINDOW + 10
        any_seen = any(now() - v["ts"] < 20 for v in seen.values())
        client.publish(f"{GW_BASE}/btrestart", json.dumps(dict(ack, status="ok" if ok_ else "error",
                       ringOk=any_seen, error=None if ok_ else "scan_failed", ts=now())), qos=1)
    except Exception as e:
        client.publish(f"{GW_BASE}/btrestart", json.dumps(dict(ack, status="error", error=str(e)[:100], ts=now())), qos=1)


def system_cmd(cmd, req):
    allowed = ALLOW_RESTART if cmd == "restart" else ALLOW_REBOOT
    ack = {"reqId": req, "gateway": GATEWAY, "ts": now()}
    if not allowed:
        client.publish(f"{GW_BASE}/{cmd}", json.dumps(dict(ack, status="error", error="not_allowed")), qos=1)
        return
    log.warning("%s demandé depuis l'admin", "Redémarrage du service" if cmd == "restart" else "Redémarrage de la machine")
    client.publish(f"{GW_BASE}/{cmd}", json.dumps(dict(ack, status="ok")), qos=1)
    client.publish(f"{GW_BASE}/status", json.dumps(status_payload(False)), qos=1, retain=True).wait_for_publish(3)
    time.sleep(1)
    if cmd == "reboot":
        subprocess.run(["systemctl", "reboot"], capture_output=True, timeout=20)
    else:
        subprocess.run(["systemctl", "--no-block", "restart", SERVICE_NAME], capture_output=True, timeout=20)
    time.sleep(30)
    shutdown()


# ---------------------------------------------------------------------------- MQTT
def on_connect(c, userdata, flags, reason_code, properties=None):
    log.info("Connecté au broker %s:%s (%s)", MQTT_HOST, MQTT_PORT, reason_code)
    c.subscribe(f"{GW_BASE}/rings", qos=1)
    c.subscribe(f"{GW_BASE}/cmd", qos=1)
    threading.Thread(target=lambda: (wan_ip(force=True), publish_status()), daemon=True).start()


def on_message(c, userdata, msg):
    try:
        p = json.loads(msg.payload.decode("utf-8") or "{}")
    except ValueError:
        return
    if not isinstance(p, dict):
        return
    if msg.topic == f"{GW_BASE}/rings":
        new = {}
        for x in p.get("rings") or []:
            mac = norm_mac((x or {}).get("mac"))
            if mac:
                new[mac] = "main" if (x or {}).get("role") == "main" else "secondary"
        rings_received["ok"] = True
        if not new and FALLBACK_MAC:
            # Aucune zone choisie pour cette gateway dans l'admin : bague du .env (RING_MAC)
            set_rings({FALLBACK_MAC: "main"}, ".env (aucune zone dans l'admin)")
        else:
            set_rings(new, "zones de l'admin")
        return
    cmd = str(p.get("cmd") or "").lower()
    if p.get("mac"):
        return   # mesure pour une bague : traitée par son instance
    req = p.get("reqId") or f"lx-{uuid.uuid4().hex[:8]}"
    if cmd == "btrestart":
        threading.Thread(target=bt_restart, args=(req,), daemon=True).start()
    elif cmd in ("restart", "reboot"):
        threading.Thread(target=system_cmd, args=(cmd, req), daemon=True).start()
    elif cmd == "ping":
        client.publish(f"{GW_BASE}/ping", json.dumps({"reqId": req, "status": "ok", "gateway": GATEWAY, "ts": now()}), qos=1)
        publish_status()


def shutdown(signum=None, frame=None):
    if stopping["v"]:
        return
    stopping["v"] = True
    log.info("Arrêt de la gateway multi-bagues")
    for mac in list(children):
        stop_child(mac, "arrêt")
    if scan["p"]:
        try:
            scan["p"].terminate()
        except Exception:
            pass
    try:
        client.publish(f"{GW_BASE}/status", json.dumps(status_payload(False)), qos=1, retain=True).wait_for_publish(2)
    except Exception:
        pass
    subprocess.run(["systemctl", "restart", "bluetooth"], capture_output=True, timeout=30)
    os._exit(0)


def main():
    os.makedirs(RUN_DIR, exist_ok=True)
    for f in ("busy.json", "seen.json"):
        try:
            os.remove(os.path.join(RUN_DIR, f))
        except OSError:
            pass
    write_macs()
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.will_set(f"{GW_BASE}/status", json.dumps({"online": False, "gateway": GATEWAY, "gatewayType": GATEWAY_TYPE,
                                                       "multi": True, "ts": now()}), qos=1, retain=True)
    client.on_connect = on_connect
    client.on_message = on_message
    client.reconnect_delay_set(1, 30)
    client.connect_async(MQTT_HOST, MQTT_PORT, keepalive=30)
    client.loop_start()
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    log.info("GATEWAY RHM Linux multi-bagues « %s » · écoute %s", GATEWAY, SCAN_PYTHON)

    # Liste des bagues : celle de l'admin (retenue) ; sans réponse en 8 s → RING_MAC du .env
    time.sleep(8)
    if not rings_received["ok"]:
        if FALLBACK_MAC:
            log.info("Aucune zone reçue de l'admin : bague du .env (RING_MAC) utilisée")
            set_rings({FALLBACK_MAC: "main"}, ".env")
        else:
            log.warning("Aucune zone reçue de l'admin et pas de RING_MAC : en attente des zones")
    if PASSIVE_SCAN:
        threading.Thread(target=scanner_loop, daemon=True).start()
    else:
        log.info("Écoute passive désactivée (PASSIVE_SCAN=0) : portée par test_reachable_v1.py")
    # Scripts utilisés par les instances bague (même .env) : vérification au démarrage
    for what, path in (("Portée", os.getenv("REACH_SCRIPT", "/root/colmi_wiss/test_reachable_v1.py")),
                       ("ALL (4 mesures)", os.getenv("MEASURE_SCRIPT", "/root/colmi_wiss/colmi_4_mesures_v3_clean.py")),
                       ("Température", os.getenv("TEMP_SCRIPT") or os.path.join(os.path.dirname(
                           os.getenv("MEASURE_SCRIPT", "/root/colmi_wiss/colmi_4_mesures_v3_clean.py")), "colmi_temperature.py"))):
        (log.info if os.path.exists(path) else log.warning)("%s : %s%s", what, path,
                                                             "" if os.path.exists(path) else " (INTROUVABLE)")
    last_status = 0
    while True:
        time.sleep(1)
        sync_children()
        clean_wants()
        b = read_busy()
        if b != busy["v"]:
            busy["v"] = b
            publish_status()
        if now() - last_status >= STATUS_EVERY:
            last_status = now()
            wan_ip()
            publish_status()


if __name__ == "__main__":
    main()
