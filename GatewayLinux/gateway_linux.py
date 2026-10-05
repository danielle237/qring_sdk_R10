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
import collections
import fcntl
import json
import urllib.request
import logging
import os
import queue
import re
import shutil
import signal
import socket
import statistics
import subprocess
import sys
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
def norm_mac(v):
    """« 30:32:42:32:64:01 », « 30-32-… » ou « 303242326401 » → « 30:32:42:32:64:01 » ; sinon ""."""
    h = re.sub(r"[^0-9A-Fa-f]", "", str(v or ""))
    if len(h) != 12 or h in ("000000000000", "FFFFFFFFFFFF"):
        return ""
    if not re.fullmatch(r"[0-9A-Fa-f:.\- ]+", str(v).strip()):
        return ""
    return ":".join(h[i:i + 2] for i in range(0, 12, 2)).upper()


RING_MAC_RAW = os.getenv("RING_MAC", "").strip()
RING_MAC = norm_mac(RING_MAC_RAW)
GATEWAY = os.getenv("GATEWAY_NAME") or socket.gethostname()
# Type de gateway annoncé au serveur (client_api) : « linux » ici, « android » pour la TV
GATEWAY_TYPE = (os.getenv("GATEWAY_TYPE") or "linux").strip().lower()
WAN_URL = os.getenv("WAN_IP_URL", "https://api.ipify.org")
# Redémarrage depuis l'admin : « restart » = service seul, « reboot » = toute la machine (0 = refusé)
ALLOW_RESTART = os.getenv("ALLOW_REMOTE_RESTART", "1") != "0"
ALLOW_REBOOT = os.getenv("ALLOW_REMOTE_REBOOT", "1") != "0"
ALLOW_BT_RESTART = os.getenv("ALLOW_REMOTE_BT_RESTART", "1") != "0"
SERVICE_NAME = os.getenv("SERVICE_NAME", "gateway-rhm")   # unité systemd (gateway-rhm.service)
CLI = os.getenv("COLMI_CLI") or shutil.which("colmi_r02_client") or os.path.expanduser("~/.local/bin/colmi_r02_client")
CMD_TIMEOUT = int(os.getenv("CMD_TIMEOUT", "90"))            # une mesure dure ~30 s
STATUS_EVERY = int(os.getenv("STATUS_SECONDS", "60"))       # statut publié (comme la TV)
# Par défaut aucune vérification BLE périodique : la Gateway annonce « en ligne + bague associée »,
# la bague n'est vérifiée que par « Actualiser » (mesure heart-rate) ou une mesure. (> 0 = « info » toutes les N s)
CHECK_EVERY = int(os.getenv("RING_CHECK_SECONDS", "0"))
VERSION = "linux-3.2"
# Fiabilité (bague appariée) : nouvelles tentatives, reset du Bluetooth, anti-clignotement de l'état
# Roaming « course » entre plusieurs Gateway Linux (même bague) : ROAMING=race
# Toutes reçoivent la commande, la première qui se connecte à la bague mesure et devient titulaire.
# v3 : plus de roaming automatique entre gateways. Le serveur (client_api) localise la bague en demandant
# le test de portée à chaque gateway à tour de rôle, puis envoie les mesures à celle au meilleur RSSI.
# (code « course » de la v2 conservé mais désactivé)
RACE = False
RACE_LOSS_DELAY = int(os.getenv("RACE_LOSS_SECONDS", "60"))    # titulaire : « hors portée » si aucune ne réussit pendant ce délai
RACE_TAKEOVER = int(os.getenv("RACE_TAKEOVER_SECONDS", "150"))  # plus de statut du titulaire → on tente de reprendre
# Passage de main : la titulaire annonce « je m'en occupe » (topic <bague>/race) ; les autres attendent
# son résultat et n'essaient que si elle échoue, ou si elle ne s'est pas annoncée dans ce délai.
RACE_CLAIM_WAIT = float(os.getenv("RACE_CLAIM_WAIT_SECONDS", "5"))
RACE_HANDOFF_MAX = int(os.getenv("RACE_HANDOFF_MAX_SECONDS", "180"))   # titulaire muette pendant sa mesure
# Bluetooth : « systemctl restart bluetooth » après chaque mesure réussie et à l'arrêt de la gateway ;
# après un échec, seulement si le boîtier n'entend plus aucun appareil (au plus 1 fois / intervalle)
BT_RESTART_AFTER_SUCCESS = os.getenv("BT_RESTART_AFTER_SUCCESS", os.getenv("BT_RESTART_AFTER_CMD", "1")) != "0"
BT_FAIL_MIN_INTERVAL = int(os.getenv("BT_RESTART_ON_FAIL_MIN_INTERVAL", "600"))
# « Actualiser » : test de portée par écoute seule (aucune connexion) avec le script de Wissem
REACH_SCRIPT = os.getenv("REACH_SCRIPT", "/root/colmi_wiss/test_reachable_v1.py")
REACH_PYTHON = os.getenv("REACH_PYTHON") or shutil.which("python3.14") or sys.executable
REACH_TIMEOUT = int(os.getenv("REACH_TIMEOUT", "25"))
REACH_WINDOW = float(os.getenv("REACH_WINDOW", "5"))
# Mesure HR / SpO2 / « all » : script de Wissem (batterie + HR + SpO2 en UNE connexion, redémarre le Bluetooth)
MEASURE_SCRIPT = os.getenv("MEASURE_SCRIPT", "/root/colmi_wiss/colmi_4_mesures_v3_clean.py")
MEASURE_TIMEOUT = int(os.getenv("MEASURE_SCRIPT_TIMEOUT", "240"))   # 4 mesures ≈ 2 min, jusqu à ~3 min
SCRIPT_CMDS = tuple(c.strip() for c in os.getenv("MEASURE_SCRIPT_CMDS", "hr,spo2,temp,all").split(",") if c.strip())
# colmi_4_mesures_v3_clean.py (HR → SpO2 → température → HRV en une connexion) ; sinon ancien wiss_test_04
FOUR_SCRIPT = "4_mesures" in os.path.basename(MEASURE_SCRIPT) or os.getenv("MEASURE_SCRIPT_KIND") == "four"
# Bouton Température : script à part (température seule), à côté de MEASURE_SCRIPT par défaut
TEMP_SCRIPT = os.getenv("TEMP_SCRIPT") or os.path.join(os.path.dirname(MEASURE_SCRIPT), "colmi_temperature.py")
if os.path.exists(TEMP_SCRIPT) and "temp" not in SCRIPT_CMDS:
    SCRIPT_CMDS += ("temp",)      # script température présent : le bouton Température l'utilise toujours
FOUR_KEYS = {"HEART RATE": "hr", "SpO2": "spo2", "TEMPERATURE": "temp", "HRV": "hrv"}
FOUR_ONLY = {"hr": "hr", "spo2": "spo2", "temp": "temperature", "hrv": "hrv", "all": "hr,spo2,temperature,hrv"}
proc = {"p": None, "kind": None, "preempted": False, "ble_waiting": 0}   # ble_waiting : mesures en file   # script en cours (test de portée / mesure)
RETRIES = int(os.getenv("BLE_RETRIES", "3"))                  # essais par commande si la connexion échoue
RETRY_DELAY = int(os.getenv("BLE_RETRY_DELAY", "4"))          # secondes entre deux essais
BT_RESET_AFTER = int(os.getenv("BT_RESET_AFTER", "2"))        # échecs de suite avant « systemctl restart bluetooth » (0 = jamais)
DISCONNECT_AFTER = int(os.getenv("DISCONNECT_AFTER", "2"))
if RACE:
    # En course : un seul essai, pas de redémarrage Bluetooth (une course perdue n'est pas une panne)
    RETRIES, BT_RESET_AFTER = 1, 0    # échecs de suite avant d'afficher « hors portée »

# Mode multi-bagues : lancé par gateway_multi.py (une instance par bague, même Pi). Le superviseur publie
# le statut de la gateway, fait l'écoute passive (scan_rings.py) et gère redémarrages ; un verrou
# partagé garantit une seule connexion Bluetooth à la fois sur le boîtier.
MULTI = os.getenv("GATEWAY_MULTI_CHILD") == "1"
RUN_DIR = os.getenv("GATEWAY_RUN_DIR", "/run/gateway-rhm")
REACH_SEEN_FRESH = int(os.getenv("REACH_SEEN_FRESH_SECONDS", "20"))
# Avant chaque mesure (multi-bagues) : écoute arrêtée → systemctl restart bluetooth → attente → mesure
BT_RESTART_BEFORE_MEASURE = os.getenv("BT_RESTART_BEFORE_MEASURE", "1") != "0"
BT_SETTLE_SECONDS = float(os.getenv("BT_SETTLE_SECONDS", "1.5"))   # écoute passive récente = « portée »
_tag = os.getenv("LOG_TAG")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s " + (f"[{_tag}] " if _tag else "") + "%(message)s")
log = logging.getLogger("gateway")

if not RING_MAC:
    # Code 78 (configuration) : systemd ne relance pas en boucle (RestartPreventExitStatus=78)
    print(f"RING_MAC {'manquant' if not RING_MAC_RAW else 'invalide (' + RING_MAC_RAW + ')'} dans .env "
          "(ex. RING_MAC=30:32:42:32:64:01) : aucune mesure possible, arrêt.", flush=True)
    raise SystemExit(78)

MAC12 = RING_MAC.replace(":", "")
BASE = f"{PREFIX}/{MAC12}"
GW_BASE = f"{PREFIX}/gateway/{re.sub(r'[^A-Za-z0-9_.-]', '_', GATEWAY)}"

# Commandes MQTT → arguments de colmi_r02_client
REALTIME = {"hr": "heart-rate", "spo2": "spo2", "hrv": "hrv", "stress": "pressure",
            "fatigue": "fatigue", "health": "health-check"}
UNITS = {"hr": "bpm", "spo2": "%", "hrv": "ms", "stress": "score", "fatigue": "score", "health": "score",
         "temp": "°C"}
UNSUPPORTED = {"temp", "bp", "sleep", "workouts", "history"}
# Sédentarité (calculée à partir des pas par tranche de 15 min) : journée 8 h → 21 h, < 30 pas = immobile
SED_START_H = int(os.getenv("SEDENTARY_START_HOUR", "8"))
SED_END_H = int(os.getenv("SEDENTARY_END_HOUR", "21"))
SED_MIN_STEPS = int(os.getenv("SEDENTARY_STEPS_PER_SLOT", "30"))

# ============================================================================ état

state = {
    "ring": "connected",        # bague associée à cette Gateway ; « disconnected » seulement après des échecs
    "worn": None,
    "battery": None,
    "charging": False,
    "firmware": "",
    "lastOk": 0,
    "measuring": None,
    "fails": 0,                 # échecs de connexion consécutifs
    # Roaming course : cette gateway est-elle titulaire de la bague (dernière à l'avoir jointe) ?
    "holder": not RACE,
    "wonTs": 0,                 # heure de la dernière course gagnée
    "winSeq": 0,                # numéro de « prise » (sans horloge) : la plus grande garde la bague
}
race_seen = {"maxSeq": 0}
done_by_other = collections.deque(maxlen=300)    # reqId réussis par une autre gateway
failed_by_holder = collections.deque(maxlen=300) # reqId où la titulaire a échoué (main passée)
claimed = {}                                     # reqId → (gateway qui s'en occupe, heure)
one_try = set()                                  # reqId : une autre gateway prend le relais → un seul essai
forced_reach = set()                             # reqId : test de portée réel demandé (multi-bagues)
BLE_CMDS = ("all", "battery", "info", "steps", "sedentary")
holder = {"name": None, "ts": 0, "type": None}   # autre Gateway Linux titulaire (vue sur le topic de la bague)
done_reqs = collections.deque(maxlen=300)        # reqId déjà traités (jamais deux fois la même mesure)
lock = threading.Lock()
jobs = queue.Queue()
# Priorité à la TV Android : si une TV annonce cette bague (associée), cette gateway passe en veille
# (plus de statut sur le topic de la bague, commandes de mesure ignorées) jusqu'à ce que la TV la libère.
OWNER_TIMEOUT = int(os.getenv("OWNER_TIMEOUT_SECONDS", "150"))
owner = {"name": None, "ts": 0}
# Localisation publiée par le serveur (retenue) : eis/colmi/<MAC>/location {"gateway", "reachable", "rssi", …}
location = {"gateway": None, "reachable": None, "rssi": None, "ts": 0}
ready = {"at": 0}   # quelques secondes après la connexion : lecture des statuts retenus avant de publier
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
            "gateway": GATEWAY, "deviceName": GATEWAY, "lanIp": lan_ip(), "wanIp": wan["ip"], "sys": sys_info(),
            "gatewayType": GATEWAY_TYPE, "appVersion": VERSION, "ts": now(),
            "roaming": "race" if RACE else None, "wonAt": state["wonTs"] or None,
            "winSeq": state["winSeq"] if RACE else None,
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


def sys_info():
    """CPU / RAM / température / disque / uptime lus dans /proc (sans dépendance)."""
    out = {}
    try:
        load1 = os.getloadavg()[0]
        out["cpu"] = round(min(100.0, load1 / (os.cpu_count() or 1) * 100), 0)   # charge 1 min en %
        out["load"] = round(load1, 2)
    except OSError:
        pass
    try:
        mem = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                mem[k] = int(v.split()[0])   # kB
        total, avail = mem.get("MemTotal", 0), mem.get("MemAvailable", 0)
        if total:
            out["ramUsedMb"] = round((total - avail) / 1024)
            out["ramTotalMb"] = round(total / 1024)
            out["ram"] = round((total - avail) * 100 / total)
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


# IP publique (WAN), comme la TV : api.ipify.org, gardée 30 min, relue à chaque (re)connexion
wan = {"ip": None, "ts": 0}


def wan_ip(force=False):
    if not force and wan["ip"] and now() - wan["ts"] < 1800:
        return wan["ip"]
    try:
        with urllib.request.urlopen(WAN_URL, timeout=5) as r:
            ip = r.read(64).decode("ascii", "ignore").strip()
        if re.fullmatch(r"[0-9a-fA-F:.]{3,45}", ip):
            wan["ip"] = ip
    except Exception as e:
        log.debug("IP WAN indisponible : %s", e)
    wan["ts"] = now()   # pas de nouvel essai avant 30 min, même en cas d'échec
    return wan["ip"]


def standby():
    return bool(owner["name"]) and now() - owner["ts"] < OWNER_TIMEOUT


def not_mine():
    """La bague a été localisée sur une AUTRE gateway : on ne publie pas son état, on n'exécute que
    les commandes adressées à notre nom."""
    return bool(location["gateway"]) and location["gateway"] != GATEWAY


def on_location(p):
    gw = p.get("gateway") or None
    changed = gw != location["gateway"] or bool(p.get("reachable")) != bool(location["reachable"])
    location.update(gateway=gw, reachable=p.get("reachable"), rssi=p.get("rssi"), ts=now())
    if gw == GATEWAY:
        with lock:
            state["ring"] = "connected" if p.get("reachable") else "disconnected"
    if changed:
        if gw == GATEWAY:
            log.info("Localisation : bague %s ici (%s)", RING_MAC,
                     f"RSSI {p.get('rssi')} dBm" if p.get("reachable") else "non entendue")
        elif gw:
            log.info("Localisation : bague %s sur « %s » → cette gateway ne mesure que sur demande", RING_MAC, gw)
        publish_status()


def publish_status():
    st = status_payload(True)
    if MULTI:
        # Multi-bagues : le statut de la gateway est publié par gateway_multi.py
        if standby() or not_mine():
            return
        if now() >= ready["at"]:
            client.publish(f"{BASE}/status", json.dumps(st), qos=1, retain=True)
        return
    if standby():
        # En veille : la bague appartient à la TV ; on ne publie que le statut de la gateway
        st.update(ring="standby", ringOwner=owner["name"], ringOwnerType="android", worn=None, measuring=None)
        client.publish(f"{GW_BASE}/status", json.dumps(st), qos=1, retain=True)
        return
    if not_mine():
        st.update(ring="standby", ringOwner=location["gateway"], ringOwnerType="linux", worn=None, measuring=None)
        client.publish(f"{GW_BASE}/status", json.dumps(st), qos=1, retain=True)
        return
    if RACE and not state["holder"]:
        # Course : une autre Gateway Linux a la bague ; on reste candidate (on reçoit les commandes)
        st.update(ring="standby", ringOwner=holder["name"], ringOwnerType="linux", worn=None, measuring=None)
        client.publish(f"{GW_BASE}/status", json.dumps(st), qos=1, retain=True)
        return
    p = json.dumps(st)
    if now() >= ready["at"]:
        client.publish(f"{BASE}/status", p, qos=1, retain=True)
    client.publish(f"{GW_BASE}/status", p, qos=1, retain=True)


def on_ring_status(p, retained=False):
    """Statut publié sur le topic de la bague par une AUTRE gateway."""
    gw = p.get("gateway")
    if not gw or gw == GATEWAY:
        return
    try:
        ts = int(p.get("ts") or 0)
    except (TypeError, ValueError):
        ts = 0
    if ts > 10 ** 11:
        ts //= 1000   # millisecondes
    typ = str(p.get("gatewayType") or "android").lower()
    if RACE and typ == "linux":
        on_linux_holder(gw, p, ts, retained)
        return
    holds = (typ != "linux" and bool(p.get("online")) and now() - ts < OWNER_TIMEOUT
             and p.get("ring") not in (None, "unbound", "no_ring", "unknown", "standby"))
    if holds:
        was = standby()
        owner.update(name=gw, ts=now())
        if not was:
            log.warning("Bague %s prise par la Gateway Android « %s » → veille (priorité Android)", RING_MAC, gw)
            publish_status()
    elif owner["name"] == gw:
        release(f"« {gw} » a libéré la bague ({'hors ligne' if not p.get('online') else p.get('ring')})")


def on_linux_holder(gw, p, ts, retained=False):
    """Course : une autre Gateway Linux annonce la bague (seule la titulaire publie ce statut).
    Sans comparer les horloges des boîtiers : la plus grande « prise » (winSeq) garde la bague."""
    try:
        seq = int(p.get("winSeq") or 0)
    except (TypeError, ValueError):
        seq = 0
    race_seen["maxSeq"] = max(race_seen["maxSeq"], seq)
    # Message retenu (ancien) : on vérifie son âge ; message en direct : toujours frais
    fresh = (not retained) or now() - ts < RACE_TAKEOVER
    if not (p.get("online") and fresh and p.get("ring") in ("connected", "disconnected")):
        if holder["name"] == gw:
            holder.update(name=None, ts=0)
        return
    # Titulaire vivante (même si la bague est hors portée : la prochaine commande passera la main)
    holder.update(name=gw, ts=now(), type="linux")
    if not state["holder"] or p.get("ring") != "connected":
        return
    mine = state["winSeq"]
    if seq > mine or (seq == mine and gw < GATEWAY):
        with lock:
            state["holder"] = False
        log.info("Course : bague %s prise par « %s » → cette gateway reste candidate", RING_MAC, gw)
        publish_status()


def won_race():
    """Cette gateway vient de joindre la bague : elle devient titulaire."""
    with lock:
        was = state["holder"]
        state["holder"], state["wonTs"] = True, now()
        if not was:
            state["winSeq"] = race_seen["maxSeq"] + 1
            race_seen["maxSeq"] = state["winSeq"]
    if RACE and not was:
        log.info("Course gagnée : cette gateway prend la bague %s", RING_MAC)
        holder.update(name=None, ts=0)
        publish_status()


def lost_contact():
    """Course : la titulaire n'a pas joint la bague. « hors portée » seulement si personne ne l'a prise
    pendant RACE_LOSS_DELAY (une autre gateway a peut-être gagné la course)."""
    failed_at = now()

    def check():
        with lock:
            still = state["holder"] and state["lastOk"] < failed_at
        if still and state["ring"] != "disconnected":
            with lock:
                state["ring"] = "disconnected"
            log.info("Course : aucune gateway n'a joint la bague %s → hors portée", RING_MAC)
            publish_status()
    threading.Timer(RACE_LOSS_DELAY, check).start()


def release(why):
    owner.update(name=None, ts=0)
    log.warning("Fin de veille : %s → cette gateway reprend la bague %s", why, RING_MAC)
    with lock:
        state["fails"] = 0
    publish_status()
    jobs.put(("sync", None))


def publish(sub, payload):
    if state.get("cancelled") and payload.get("status") == "error" and payload.get("reqId") \
            and str(payload.get("reqId")).split("-hr")[0].split("-spo2")[0].split("-battery")[0] == state.get("curReq"):
        payload["error"] = "cancelled"      # mesure annulée par l'utilisateur
    payload.setdefault("ts", now())
    payload.setdefault("ringMac", RING_MAC)
    payload.setdefault("gateway", GATEWAY)
    if RACE:
        payload.setdefault("roaming", "race")   # le serveur attend les autres gateways avant d'afficher une erreur
    client.publish(f"{BASE}/{sub}", json.dumps(payload), qos=1)


# ============================================================================ Bluetooth (colmi_r02_client)

def run_cli(*args):
    """(code, texte) — texte = sortie standard + erreurs."""
    ensure_bt_on()
    if not norm_mac(RING_MAC):
        # Sécurité : jamais de commande Bluetooth sans adresse de bague valide
        log.error("Commande refusée : adresse de bague vide ou invalide (%r)", RING_MAC)
        return -4, "not found: no ring address"
    state["bleUsed"] = True
    cmd = [CLI, "--address", RING_MAC, *args]
    log.info("→ %s", " ".join(cmd[1:]))
    if state.get("cancelled"):
        return -5, "cancelled"
    try:
        pr = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        proc.update(p=pr, kind="cli")
        try:
            o, e = pr.communicate(timeout=CMD_TIMEOUT)
        except subprocess.TimeoutExpired:
            pr.kill()
            pr.communicate()
            raise
        finally:
            proc.update(p=None, kind=None)

        class _R:      # même forme que subprocess.run
            returncode, stdout, stderr = pr.returncode, o, e
        r = _R()
        if state.get("cancelled"):
            log.info("← commande arrêtée (mesure annulée)")
            return -5, "cancelled"
        out = (r.stdout or "") + (r.stderr or "")
        if "Traceback" in out:
            # Plantage de colmi_r02_client : la dernière ligne dit la vraie cause (ex. BleakDeviceNotFoundError)
            last = [l.strip() for l in out.strip().splitlines() if l.strip()][-1:]
            log.info("← erreur colmi_r02_client : %s", (last[0] if last else "?")[:300])
        else:
            log.info("← %s", out.strip().replace("\n", " | ")[:300])
        return r.returncode, out
    except subprocess.TimeoutExpired:
        return -1, "timeout"
    except FileNotFoundError:
        return -2, f"colmi_r02_client introuvable ({CLI})"


def bt_reset():
    """Échecs de suite : « systemctl restart bluetooth » (le service rallume l'adaptateur)."""
    restart_bluetooth(f"{BT_RESET_AFTER}ᵉ erreur de suite")


def run_ring(*args):
    """Comme run_cli, mais réessaie si la bague n'a pas répondu (connexion) et relance le Bluetooth
    après plusieurs échecs. Pas de nouvel essai si la bague a répondu « non portée »."""
    code, out = -3, ""
    tries = 1 if state.get("oneTry") else max(1, RETRIES)
    for attempt in range(1, tries + 1):
        if state.get("cancelled"):
            return -5, "cancelled"
        code, out = run_cli(*args)
        err = None if code == 0 and "error" not in out.lower() else error_code(out, code)
        if err == "bluetooth_off":
            # Adaptateur éteint (pas la bague) : on le rallume et on réessaie tout de suite
            if ensure_bt_on("colmi_r02_client"):
                code, out = run_cli(*args)
                err = None if code == 0 and "error" not in out.lower() else error_code(out, code)
            if err == "bluetooth_off":
                return code, out
        if err not in ("ring_disconnected", "timeout"):
            with lock:
                state["fails"] = 0
            return code, out
        with lock:
            state["fails"] += 1
        # 2ᵉ erreur de cette commande → systemctl restart bluetooth, puis dernier essai
        if BT_RESET_AFTER and attempt == BT_RESET_AFTER and attempt < tries:
            bt_reset()
        if attempt < tries:
            log.info("Bague injoignable (essai %s/%s), nouvel essai dans %s s", attempt, RETRIES, RETRY_DELAY)
            time.sleep(RETRY_DELAY)
    return code, out


def parse_values(out):
    """« [70, 69, 69, 68] » → [70, 69, 69, 68] (valeurs > 0 seulement)."""
    m = re.findall(r"\[([0-9,\s.]+)\]", out)
    if not m:
        return []
    return [float(x) for x in m[-1].split(",") if x.strip() and float(x) > 0]


BT_OFF_WORDS = ("no powered bluetooth", "powered_off", "bluetoothnotavailable", "bluetooth device is turned off",
                "not ready", "no bluetooth adapters")


def error_code(out, code):
    if code == -5:
        return "cancelled"
    return _error_code(out, code)


def _error_code(out, code):
    t = out.lower()
    if any(w in t for w in BT_OFF_WORDS):
        return "bluetooth_off"
    if "worn" in t or "no heart rate" in t or "no data" in t:
        return "ring_removed"
    if code == -1 or "timeout" in t:
        return "timeout"
    if any(w in t for w in ("not found", "failed to connect", "no device", "bleak", "disconnected", "could not")):
        return "ring_disconnected"
    return "measure_failed"


def set_ring(ok, worn=None):
    if RACE:
        if ok:
            with lock:
                state["ring"], state["lastOk"] = "connected", now()
                if worn is not None:
                    state["worn"] = worn
            won_race()
        else:
            if worn is not None:
                with lock:
                    state["worn"] = worn
            if state["holder"]:
                lost_contact()
        return
    with lock:
        if ok:
            state["ring"], state["lastOk"] = "connected", now()
        elif MULTI:
            # Multi-bagues : « hors portée » est décidé par test_reachable_v1.py (via client_api),
            # pas par un échec de mesure
            pass
        elif state["fails"] >= DISCONNECT_AFTER or state["ring"] != "connected":
            # « hors portée » seulement après plusieurs échecs (pas au premier raté)
            state["ring"] = "disconnected"
        if worn is not None:
            state["worn"] = worn


def measure(key):
    """(valeur, liste, erreur) pour hr / spo2 / hrv / stress."""
    code, out = run_ring("get-real-time", REALTIME[key])
    vals = parse_values(out)
    if vals:
        value = round(statistics.median(vals))
        set_ring(True, worn=True)
        return value, vals, None
    err = error_code(out, code)
    if err == "cancelled":
        return None, [], err          # annulée : l'état de la bague ne change pas
    set_ring(err in ("ring_removed", "measure_failed"), worn=False if err == "ring_removed" else None)
    return None, [], err


def read_info():
    """Batterie + firmware avec « info ». True si la bague a répondu."""
    # device info {'hw_version': 'RT03CR_V1.0', 'fw_version': 'RT03CR_1.00.01_250104'}
    # battery: BatteryInfo(battery_level=83, charging=False)
    code, out = run_ring("info")
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
    code, out = run_ring("get-steps")
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

def do_reach(req):
    """Test de portée : lance test_reachable_v1.py (écoute seule, pas de connexion à la bague).
    Demandé par le serveur à chaque gateway à tour de rôle ; pas de redémarrage Bluetooth."""
    base = {"reqId": req, "source": "mqtt"}
    if not os.path.exists(REACH_SCRIPT):
        log.error("Script de portée introuvable : %s", REACH_SCRIPT)
        publish("reach", dict(base, status="error", error="not_supported"))
        return
    publish("reach", dict(base, status="measuring"))
    ensure_bt_on("test de portée")
    args = [REACH_PYTHON, REACH_SCRIPT, "--mac", RING_MAC, "--window", str(REACH_WINDOW), "--json",
            "--gateway", GATEWAY]
    log.info("→ portée : %s", " ".join(args[1:]))

    def run_once():
        try:
            pr = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            proc.update(p=pr, kind="reach")
            try:
                o, _ = pr.communicate(timeout=REACH_TIMEOUT)
            except subprocess.TimeoutExpired:
                pr.kill()
                o, _ = pr.communicate()
            return o or ""
        except OSError as e:
            return f"STATUS : ERROR ({e})"
        finally:
            proc.update(p=None, kind=None)

    out = run_once()
    if not proc["preempted"] and any(w in out.lower() for w in BT_OFF_WORDS):
        # Adaptateur éteint : on le rallume et on refait le test une fois
        if ensure_bt_on("test de portée : adaptateur éteint"):
            out = run_once()
    if proc["preempted"]:
        # Arrêté pour laisser passer une mesure
        log.info("← portée : test arrêté (mesure demandée)")
        publish("reach", dict(base, status="error", error="cancelled"))
        return
    res = {}
    m = re.search(r"RESULT_JSON\s+(\{.*\})", out)
    if m:
        try:
            res = json.loads(m.group(1))
        except ValueError:
            res = {}
    if not res:   # ancienne version du script (sans --json) : lecture du texte
        st = re.search(r"STATUS\s*:\s*([A-Z_]+)", out)
        rssi = re.search(r"RSSI\s*[:=]\s*(-?\d+)", out)
        first = re.search(r"FIRST SEEN\s*:\s*([\d.]+)", out)
        res = {"status": st.group(1) if st else "ERROR", "rssi": int(rssi.group(1)) if rssi else None,
               "first_seen": float(first.group(1)) if first else None}
    status = res.get("status") or "ERROR"
    log.info("← portée : %s%s", status, f" · RSSI {res.get('rssi')} dBm" if res.get("rssi") is not None else "")
    if status == "REACHABLE":
        publish("reach", dict(base, status="ok", reachable=True, value=res.get("rssi"), rssi=res.get("rssi"),
                              unit="dBm", firstSeen=res.get("first_seen")))
    elif status == "NOT_AVAILABLE":
        publish("reach", dict(base, status="error", error="ring_disconnected"))
    else:
        log.warning("Test de portée en erreur : %s", out.strip()[-300:])
        publish("reach", dict(base, status="error", error="measure_failed"))


def run_four_script(cmd, req):
    """HR / SpO2 / T° / all : colmi_4_mesures_v3_clean.py (une connexion : HR → SpO2 → température → HRV).
    Lit la sortie du script ligne par ligne : chaque valeur est publiée dès qu'elle est mesurée.
      SUCCESS            → toutes les valeurs enregistrées
      NON_WORN           → bague retirée (rien d'autre n'est mesuré)
      CONNECT_FAILED /
      CONNECTION_LOST    → hors portée, puis test de portée (test_reachable_v1.py / écoute passive)
      TIMEOUT / ERROR    → mesure échouée"""
    req = req or f"lx-{uuid.uuid4().hex[:8]}"
    base = {"reqId": req, "source": "mqtt"}
    if proc.pop("preempted", False) or proc.get("restart_needed"):
        proc["restart_needed"] = False
        restart_bluetooth("test de portée arrêté avant la mesure")
    proc["preempted"] = False
    with lock:
        state["measuring"] = cmd
    publish_status()
    ensure_bt_on("mesure")
    state["bleUsed"] = True
    args = [REACH_PYTHON, MEASURE_SCRIPT, "--mac", RING_MAC, "--only", FOUR_ONLY.get(cmd, cmd), "--json"]
    if cmd == "temp" and os.path.exists(TEMP_SCRIPT):
        args = [REACH_PYTHON, TEMP_SCRIPT, "--mac", RING_MAC, "--json"]
    elif cmd == "temp":
        log.warning("Script température introuvable (%s) : script 4 mesures utilisé", TEMP_SCRIPT)
    log.info("→ mesure : %s", " ".join(args[1:]))
    started = now()
    sub_req = lambda k: req if k == cmd else f"{req}-{k}"
    samples, published, current, res, lines = {}, set(), {"k": None, "t": 0}, {}, []

    def finish_key(k):
        vals = samples.get(k) or []
        if k in published or len(vals) < 6:
            return
        published.add(k)
        v = round(statistics.median(vals), 1) if k == "temp" else round(statistics.median(vals))
        publish(k, {"reqId": sub_req(k), "source": "mqtt", "status": "ok", "value": v, "values": vals,
                    "unit": UNITS.get(k, ""), "_dur": now() - current["t"] if current["t"] else None})
        log.info("← %s = %s %s", k, v, UNITS.get(k, ""))

    def run_once():
        res.clear()
        lines.clear()
        try:
            pr = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            proc.update(p=pr, kind="measure")
            killer = threading.Timer(MEASURE_TIMEOUT, lambda: pr.kill())
            killer.start()
            try:
                for line in pr.stdout:
                    lines.append(line)
                    line = line.strip()
                    if line.startswith("RESULT_JSON "):
                        try:
                            res.update(json.loads(line[12:]))
                        except ValueError:
                            res.clear()
                        continue
                    m = re.search(r"\|\s*(HEART RATE|SpO2|TEMPERATURE|HRV) (START|SAMPLE|STOP|ERROR|TIMEOUT)\b(.*)", line)
                    if not m:
                        continue
                    k, ev, rest = FOUR_KEYS[m.group(1)], m.group(2), m.group(3)
                    if ev == "START":
                        current.update(k=k, t=now())
                        samples[k] = []
                        publish(k, {"reqId": sub_req(k), "source": "mqtt", "status": "measuring"})
                    elif ev == "SAMPLE":
                        sm = re.search(r"\|\s*(-?\d+(?:\.\d+)?)", rest)
                        if sm:
                            samples.setdefault(k, []).append(float(sm.group(1)))
                    elif ev == "STOP":
                        finish_key(k)
                pr.wait()
            finally:
                killer.cancel()
        except OSError as e:
            log.warning("Mesure : script impossible : %s", e)
        finally:
            proc.update(p=None, kind=None)

    # 1/3 et 2/3 : mesure normale ; 3/3 : redémarrage du Bluetooth puis mesure. Nouvel essai seulement si la
    # bague n'a pas répondu (connexion impossible / perdue) et qu'aucune valeur n'a encore été publiée.
    tries = 1 if state.get("oneTry") else max(1, RETRIES)
    for attempt in range(1, tries + 1):
        if attempt > 1:
            if BT_RESET_AFTER and attempt == BT_RESET_AFTER + 1:
                log.info("Mesure %s/%s : redémarrage du Bluetooth puis mesure", attempt, tries)
                restart_bluetooth(f"mesure {cmd} : {attempt - 1} essais sans réponse de la bague")
                wait_bt_ready()
            else:
                log.info("Mesure %s/%s dans %s s (bague injoignable)", attempt, tries, RETRY_DELAY)
                time.sleep(RETRY_DELAY)
            if state.get("cancelled"):
                break
        run_once()
        st_ = res.get("status") or ("CONNECT_FAILED" if any("CONNECT FAILED" in l for l in lines) else "ERROR")
        if state.get("cancelled") or published or st_ not in ("CONNECT_FAILED", "CONNECTION_LOST"):
            break
        log.info("Mesure %s/%s : bague injoignable (%s)", attempt, tries, st_)
    with lock:
        state["measuring"] = None
    if state.get("cancelled"):
        log.info("← mesure annulée par l'utilisateur")
        publish(cmd, dict(base, status="error", error="cancelled"))
        return
    status = res.get("status") or ("CONNECT_FAILED" if any("CONNECT FAILED" in l for l in lines) else "ERROR")
    for k, r in (res.get("results") or {}).items():       # valeurs complètes non encore publiées
        k = "temp" if k == "temperature" else k
        if r.get("ok") and k not in published and r.get("samples"):
            samples[k] = [float(x) for x in r["samples"]]
            finish_key(k)
    log.info("← mesure : %s%s · %s", status, f" (à {res.get('failed_at')})" if res.get("failed_at") else "",
             ", ".join(sorted(published)) or "aucune valeur")
    wanted = ["hr", "spo2", "temp", "hrv"] if cmd == "all" else [cmd]
    missing = [k for k in wanted if k not in published]
    if status == "SUCCESS" or (published and not missing):
        set_ring(True, worn=True)
        if cmd == "all":
            publish("all", dict(base, status="ok", _dur=now() - started))   # valeurs déjà envoyées une à une
    else:
        if status == "NON_WORN":
            set_ring(True, worn=False)
            err = "ring_removed"
        elif status in ("CONNECT_FAILED", "CONNECTION_LOST"):
            set_ring(False)
            err = "ring_disconnected"
        elif status == "MEASUREMENT_TIMEOUT":
            set_ring(True)
            err = "timeout"
        else:
            err = "measure_failed"
        if published and status != "NON_WORN":
            set_ring(True, worn=True)
        for k in missing:
            if k != cmd:
                publish(k, {"reqId": sub_req(k), "source": "mqtt", "status": "error", "error": err})
        publish(cmd, dict(base, status="error", error=err, partial=sorted(published) or None))
        if err == "ring_disconnected":
            # Hors portée (« REACHABILITY_RECOMMENDED ») : on relance le test de portée
            log.info("Bague non jointe → test de portée")
            if not MULTI:            # multi-bagues : client_api lance le test sur toutes les zones
                do_reach(f"{req}-reach")
    publish_status()


def run_measure_script(cmd, req):
    """HR / SpO2 / all : lance wiss_test_04_fast_one_connection.py (une connexion : batterie, HR, SpO2)
    et publie les résultats sur les topics habituels. Le script redémarre lui-même le Bluetooth."""
    base = {"reqId": req, "source": "mqtt"}
    if proc.pop("preempted", False) or proc.get("restart_needed"):
        proc["restart_needed"] = False
        restart_bluetooth("test de portée arrêté avant la mesure")
    proc["preempted"] = False
    with lock:
        state["measuring"] = cmd
    # Pas d'annonce « <cmd> en cours » ici : le script annonce chaque mesure dans l'ordre réel
    # (HR d'abord, puis SpO2), même quand l'app a demandé la SpO2
    publish_status()
    ensure_bt_on("mesure")
    # --live : le script envoie lui-même début / fin de chaque mesure, avec le reqId de l'app qui l'a demandée
    args = [REACH_PYTHON, MEASURE_SCRIPT, "--mac", RING_MAC, "--gateway", GATEWAY, "--json", "--no-mqtt",
            "--live", "--req", req or f"lx-{uuid.uuid4().hex[:8]}", "--cmd", cmd]
    log.info("→ mesure : %s", " ".join(args[1:]))
    started = now()
    res = {}
    try:
        pr = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        proc.update(p=pr, kind="measure")
        try:
            out, _ = pr.communicate(timeout=MEASURE_TIMEOUT)
        except subprocess.TimeoutExpired:
            pr.kill()
            out, _ = pr.communicate()
        m = re.search(r"RESULT_JSON\s+(\{.*\})", out or "")
        if m:
            res = json.loads(m.group(1))
        else:
            log.warning("Mesure : pas de résultat du script : %s", (out or "").strip()[-300:])
    except (OSError, ValueError) as e:
        log.warning("Mesure : script impossible : %s", e)
    finally:
        proc.update(p=None, kind=None)
        with lock:
            state["measuring"] = None
    if state.get("cancelled"):
        log.info("← mesure annulée par l'utilisateur")
        publish(cmd, dict(base, status="error", error="cancelled"))
        return
    status = res.get("status") or "ERROR"
    hr, spo2 = res.get("hr") or [], res.get("spo2") or []
    log.info("← mesure : %s · batterie %s · HR %s · SpO2 %s", status, res.get("battery"), hr, spo2)
    dur = now() - started
    if res.get("live"):
        # Résultats déjà envoyés en direct par le script : on met seulement à jour l'état de la gateway
        if res.get("battery") is not None:
            with lock:
                state["battery"], state["charging"] = res["battery"], bool(res.get("charging"))
        if status == "ACCESSIBLE_PORTEE":
            set_ring(True, worn=True)
        elif status == "ACCESSIBLE_NON_PORTEE":
            set_ring(True, worn=False)
        elif status == "NOT_AVAILABLE":
            set_ring(False)
        publish_status()
        return
    if res.get("battery") is not None:
        with lock:
            state["battery"], state["charging"] = res["battery"], bool(res.get("charging"))
        publish("battery", {"reqId": f"{req}-bat", "status": "ok", "value": res["battery"],
                            "charging": bool(res.get("charging")), "unit": "%"})
    med = lambda v: round(statistics.median(v)) if v else None
    if status == "ACCESSIBLE_PORTEE":
        set_ring(True, worn=True)
        h, o = med(hr), med(spo2)
        if cmd == "all":
            publish("all", dict(base, status="ok", **{k: v for k, v in (("hr", h), ("spo2", o)) if v is not None}))
        else:
            main_v, main_list, unit = (h, hr, "bpm") if cmd == "hr" else (o, spo2, "%")
            if main_v is not None:
                publish(cmd, dict(base, status="ok", value=main_v, values=main_list, unit=unit, _dur=dur))
            else:
                publish(cmd, dict(base, status="error", error="measure_failed"))
            # L'autre valeur, mesurée sur la même connexion, est aussi envoyée
            other, ov, ol, ou = ("spo2", o, spo2, "%") if cmd == "hr" else ("hr", h, hr, "bpm")
            if ov is not None:
                publish(other, {"reqId": f"{req}-{other}", "status": "ok", "value": ov, "values": ol, "unit": ou})
    elif status == "ACCESSIBLE_NON_PORTEE":
        set_ring(True, worn=False)
        publish(cmd, dict(base, status="error", error="ring_removed"))
    elif status == "NOT_AVAILABLE":
        set_ring(False)
        publish(cmd, dict(base, status="error", error="ring_disconnected"))
    else:
        publish(cmd, dict(base, status="error", error="measure_failed"))
    publish_status()


def wait_for_holder(cmd, req):
    """Gateway qui n'a pas la main : attend la titulaire. True = à nous d'essayer."""
    t0 = time.time()
    while True:
        if req in done_by_other:
            log.info("Commande %s (%s) faite par « %s » : rien à faire", cmd, req, holder["name"] or "la titulaire")
            return False
        if req in failed_by_holder:
            log.info("Commande %s (%s) : la titulaire a échoué → cette gateway prend le relais", cmd, req)
            return True
        c = claimed.get(req)
        waited = time.time() - t0
        if not c and waited >= RACE_CLAIM_WAIT:
            log.info("Commande %s (%s) : aucune titulaire ne s'est annoncée en %ss → cette gateway essaie",
                     cmd, req, int(RACE_CLAIM_WAIT))
            return True
        if c and waited >= RACE_HANDOFF_MAX:
            log.info("Commande %s (%s) : « %s » ne répond plus → cette gateway essaie", cmd, req, c[0])
            return True
        time.sleep(0.2)


def handle(cmd, req):
    base = {"reqId": req, "source": "mqtt"}
    if cmd in SCRIPT_CMDS or cmd in REALTIME or cmd in BLE_CMDS:
        proc["ble_waiting"] = max(0, proc.get("ble_waiting", 0) - 1)
    if cmd == "reach":
        if standby():
            return
        if proc.get("ble_waiting", 0) > 0:
            # Une mesure attend dans la file : le test de portée lui laisse la place
            log.info("Portée (%s) : mesure en attente → test annulé", req)
            publish("reach", {"reqId": req, "source": "mqtt", "status": "error", "error": "cancelled"})
            return
        do_reach(req)
        return
    if cmd in SCRIPT_CMDS and not standby() and (os.path.exists(MEASURE_SCRIPT)
                                                  or (cmd == "temp" and os.path.exists(TEMP_SCRIPT))):
        if req:
            key = f"{cmd}:{req}"
            if key in done_reqs:
                return
            done_reqs.append(key)
        if FOUR_SCRIPT or (cmd == "temp" and os.path.exists(TEMP_SCRIPT)):
            run_four_script(cmd, req)
        else:
            run_measure_script(cmd, req)
        return
    is_ble = cmd in REALTIME or cmd in BLE_CMDS
    if is_ble and (proc.get("restart_needed") or proc.get("preempted")):
        # Test de portée arrêté pour cette commande : Bluetooth redémarré avant (comme pour HR / SpO2)
        proc["restart_needed"] = proc["preempted"] = False
        restart_bluetooth("test de portée arrêté avant la mesure")
    if RACE and is_ble and req and not standby():
        if state["holder"]:
            # Titulaire : « je m'en occupe » (les autres attendent mon résultat)
            client.publish(f"{BASE}/race", json.dumps({"reqId": req, "cmd": cmd, "event": "claim",
                                                       "gateway": GATEWAY, "ts": now()}), qos=1)
        elif not wait_for_holder(cmd, req):
            return
    if req and cmd not in ("sync", "info-silent", "btrestart"):
        key = f"{cmd}:{req}"
        if key in done_reqs:
            log.info("Commande %s (%s) déjà traitée : ignorée", cmd, req)
            return
        done_reqs.append(key)
    if standby() and cmd not in ("sync", "btrestart", "ping"):
        log.info("Commande %s ignorée : bague prise par « %s » (priorité Android)", cmd, owner["name"])
        return
    if cmd == "sync":
        wait = ready["at"] - now()
        if wait > 0:
            time.sleep(wait)
        if standby() or not_mine():
            publish_status()
            return
        if RACE and not state["holder"] and holder["name"] and now() - holder["ts"] < RACE_TAKEOVER:
            # Une autre Gateway Linux a déjà la bague : pas de connexion, on reste candidate
            publish_status()
            return
        # Démarrage : synchronisation vers le Client RHM / l'admin (statut + batterie publiés)
        publish_status()
        if MULTI:
            # Multi-bagues : pas de connexion à la bague au démarrage (« info ») ; batterie lue à la demande
            return
        if read_info():
            with lock:
                b, ch = state["battery"], state["charging"]
            if b is not None:
                publish("battery", {"reqId": f"lx-sync-{uuid.uuid4().hex[:6]}", "status": "ok",
                                    "value": b, "charging": ch, "unit": "%"})
        publish_status()
        return
    if cmd == "btrestart":
        # Admin : redémarrage du service Bluetooth de la machine, puis test de la bague
        ack = {"reqId": req, "gateway": GATEWAY}
        if not ALLOW_BT_RESTART:
            client.publish(f"{GW_BASE}/btrestart", json.dumps(dict(ack, status="error", error="not_allowed", ts=now())), qos=1)
            return
        log.warning("Redémarrage du service Bluetooth demandé depuis l'admin (%s)", req)
        client.publish(f"{GW_BASE}/btrestart", json.dumps(dict(ack, status="running", ts=now())), qos=1)
        ok_ = True
        try:
            r = subprocess.run(["systemctl", "restart", "bluetooth"], capture_output=True, text=True, timeout=30)
            ok_ = r.returncode == 0
            time.sleep(5)
            subprocess.run(["bluetoothctl", "power", "on"], capture_output=True, timeout=10)
            subprocess.run(["bluetoothctl", "trust", RING_MAC], capture_output=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            ok_ = False
        with lock:
            state["fails"] = 0
        ring_ok = read_info()   # la bague répond-elle après le redémarrage ?
        client.publish(f"{GW_BASE}/btrestart", json.dumps(dict(ack, status="ok" if ok_ else "error",
                       error=None if ok_ else "bluetooth_restart_failed", ringOk=ring_ok, ts=now())), qos=1)
        publish_status()
        return
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


def bt_powered():
    try:
        r = subprocess.run(["bluetoothctl", "show"], capture_output=True, text=True, timeout=10)
        return "Powered: yes" in (r.stdout or "")
    except (OSError, subprocess.TimeoutExpired):
        return True   # bluetoothctl absent : on ne bloque pas


def ensure_bt_on(why=""):
    """Adaptateur Bluetooth allumé ? Sinon « bluetoothctl power on » (BlueZ peut redémarrer adaptateur éteint).
    En dernier recours : systemctl restart bluetooth + power on."""
    if bt_powered():
        return True
    log.warning("Adaptateur Bluetooth éteint%s → power on", f" ({why})" if why else "")
    for attempt in range(2):
        for _ in range(5):
            try:
                subprocess.run(["bluetoothctl", "power", "on"], capture_output=True, timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                pass
            time.sleep(1)
            if bt_powered():
                log.info("Adaptateur Bluetooth allumé")
                return True
        if attempt == 0:
            log.warning("Adaptateur toujours éteint → systemctl restart bluetooth")
            try:
                subprocess.run(["systemctl", "restart", "bluetooth"], capture_output=True, timeout=30)
            except (OSError, subprocess.TimeoutExpired):
                pass
            time.sleep(3)
    log.error("Impossible d'allumer l'adaptateur Bluetooth (rfkill ? matériel ?)")
    return False


def restart_bluetooth(why):
    """systemctl restart bluetooth, puis adaptateur rallumé si BlueZ l'a laissé éteint."""
    log.info("Redémarrage du service Bluetooth (%s)", why)
    state["lastBtRestart"] = now()
    try:
        subprocess.run(["systemctl", "restart", "bluetooth"], check=False, capture_output=True, timeout=30)
        time.sleep(2)
    except (OSError, subprocess.TimeoutExpired) as e:
        log.warning("Redémarrage Bluetooth impossible : %s", e)
    ensure_bt_on("après redémarrage")


def scan_diag():
    """Écoute 3 s (sans connexion) : (nombre d'appareils entendus, bague entendue ?) ; (None, None) si le scan plante."""
    # Python avec bleak : SCAN_PYTHON, sinon python3.14 (comme test_reachable_v1.py)
    py = (shutil.which(os.getenv("SCAN_PYTHON") or "") or os.getenv("SCAN_PYTHON")
          or shutil.which("python3.14") or sys.executable)
    code = ("import asyncio,json,sys\nfrom bleak import BleakScanner\n"
            "async def m():\n d=await BleakScanner.discover(timeout=3)\n"
            " print(json.dumps([x.address.upper() for x in d]))\nasyncio.run(m())")
    try:
        r = subprocess.run([py, "-c", code], capture_output=True, text=True, timeout=20)
        addrs = json.loads((r.stdout or "").strip().splitlines()[-1])
        return len(addrs), RING_MAC in addrs
    except Exception:
        return None, None


def after_command(cmd, started):
    """Fin de commande : redémarrage Bluetooth selon le résultat."""
    if not state.get("bleUsed") or cmd == "btrestart":
        return
    if state["lastOk"] >= started:
        if BT_RESTART_AFTER_SUCCESS and not (MULTI and state.get("lastBtRestart", 0) >= started):
            restart_bluetooth(f"fin de {cmd} (réussie)")
        return
    if MULTI:
        # Multi-bagues : Bluetooth redémarré au 3ᵉ essai OU à la fin de la mesure (une seule fois)
        if state.get("lastBtRestart", 0) >= started:
            log.info("Fin de %s (échec) : Bluetooth déjà redémarré pendant la mesure", cmd)
        else:
            restart_bluetooth(f"fin de {cmd} (échec)")
        return
    # Échec : Bluetooth planté ou bague non joignable ?
    n, ring_seen = scan_diag()
    if ring_seen:
        log.info("Échec %s : bague entendue mais connexion impossible → connexion difficile, pas de redémarrage", cmd)
    elif n:
        log.info("Échec %s : Bluetooth OK (%s appareils entendus) → bague non joignable, pas de redémarrage", cmd, n)
    elif now() - state.get("lastBtFailRestart", 0) >= BT_FAIL_MIN_INTERVAL:
        state["lastBtFailRestart"] = now()
        restart_bluetooth(f"échec de {cmd} : aucun appareil entendu (Bluetooth planté ?)")
    else:
        log.info("Échec %s : aucun appareil entendu, redémarrage Bluetooth déjà fait il y a moins de %s min",
                 cmd, BT_FAIL_MIN_INTERVAL // 60)


# ---------------------------------------------------------------- verrou Bluetooth (mode multi-bagues)
bt_lock = {"f": None}


def bt_acquire(cmd, req):
    """Attend son tour pour le Bluetooth du boîtier (une seule connexion à la fois). L'écoute passive
    voit le fichier « want » et s'arrête tout de suite pour laisser passer la mesure."""
    if not MULTI:
        return
    want = os.path.join(RUN_DIR, f"want-{MAC12}")
    try:
        os.makedirs(RUN_DIR, exist_ok=True)
        with open(want, "w") as w:
            w.write(str(os.getpid()))
        f = open(os.path.join(RUN_DIR, "bt.lock"), "a+")
        t0 = time.time()
        fcntl.flock(f, fcntl.LOCK_EX)
        waited = time.time() - t0
        if waited > 3:
            log.info("Bluetooth libre après %.0f s d'attente (autre bague du boîtier)", waited)
        bt_lock["f"] = f
        tmp = os.path.join(RUN_DIR, f".busy-{MAC12}")
        with open(tmp, "w") as b:
            json.dump({"mac": RING_MAC, "cmd": cmd, "reqId": req, "pid": os.getpid(), "ts": now()}, b)
        os.replace(tmp, os.path.join(RUN_DIR, "busy.json"))
    except OSError as e:
        log.warning("Verrou Bluetooth indisponible (%s) : on continue sans", e)
    finally:
        try:
            os.remove(want)
        except OSError:
            pass
    if cmd not in ("sync", "info-silent", "reach") and BT_RESTART_BEFORE_MEASURE:
        # Écoute passive arrêtée : Bluetooth redémarré et prêt AVANT de se connecter à la bague
        # (sinon la connexion peut rester bloquée sur « Connexion à la bague… »)
        restart_bluetooth("écoute passive arrêtée avant la mesure")
        wait_bt_ready()


def wait_bt_ready(timeout=15):
    """Attend que l'adaptateur soit de nouveau allumé et prêt après un redémarrage."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        if bt_powered():
            time.sleep(BT_SETTLE_SECONDS)          # laisse BlueZ finir de démarrer
            log.info("Bluetooth prêt (%.0f s) → mesure", time.time() - t0)
            return True
        ensure_bt_on("attente avant la mesure")
        time.sleep(1)
    log.warning("Bluetooth pas prêt après %s s : mesure tentée quand même", timeout)
    return False


def bt_release():
    f = bt_lock.pop("f", None)
    bt_lock["f"] = None
    if not f:
        return
    try:
        os.remove(os.path.join(RUN_DIR, "busy.json"))
    except OSError:
        pass
    try:
        fcntl.flock(f, fcntl.LOCK_UN)
        f.close()
    except OSError:
        pass


def cancel_measures(req):
    kept, dropped = [], []
    while True:
        try:
            job = jobs.get_nowait()
        except queue.Empty:
            break
        (dropped if job[0] in SCRIPT_CMDS or job[0] in REALTIME or job[0] in BLE_CMDS else kept).append(job)
    for job in kept:
        jobs.put(job)
    for c, r in dropped:
        proc["ble_waiting"] = max(0, proc.get("ble_waiting", 0) - 1)
        publish(c, {"reqId": r, "source": "mqtt", "status": "error", "error": "cancelled"})
    running = state.get("busyCmd")
    if running:
        state["cancelled"] = True
        p = proc.get("p")
        if p is not None and proc.get("kind") in ("cli", "measure"):
            try:
                p.terminate()
            except Exception:
                pass
    log.info("Annulation (%s) : %s%s", req, f"mesure {running} arrêtée" if running else "aucune mesure en cours",
             f", {len(dropped)} en file retirée(s)" if dropped else "")


def seen_reach(req):
    """Multi-bagues : réponse au test de portée d'après l'écoute passive (aucune connexion, immédiat)."""
    base = {"reqId": req, "source": "mqtt"}
    try:
        with open(os.path.join(RUN_DIR, "seen.json")) as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = None
    if not data or now() - int(data.get("scanTs") or 0) > 60:
        return False   # écoute passive arrêtée : test de portée classique
    e = (data.get("rings") or {}).get(RING_MAC) or {}
    age = now() - int(e.get("ts") or 0)
    if e.get("rssi") is not None and age <= REACH_SEEN_FRESH:
        log.info("Portée (%s) : entendue il y a %s s · RSSI %s dBm (écoute passive)", req, age, e["rssi"])
        publish("reach", dict(base, status="ok", reachable=True, value=e["rssi"], rssi=e["rssi"], unit="dBm",
                              seenAgo=age, passive=True))
    else:
        log.info("Portée (%s) : non entendue depuis %s (écoute passive)", req, f"{age} s" if e else "le démarrage")
        publish("reach", dict(base, status="error", error="ring_disconnected", passive=True))
    return True


def worker():
    while True:
        cmd, req = jobs.get()
        state["busyCmd"] = cmd if cmd not in ("reach", "sync", "info-silent", "btrestart") else None
        state["bleUsed"] = False
        state["cancelled"] = False
        state["curReq"] = req
        state["oneTry"] = req in one_try
        one_try.discard(req)
        started = now()
        if MULTI and cmd == "reach" and req not in forced_reach and seen_reach(req):
            state["busyCmd"] = None
            continue
        if MULTI:
            bt_acquire(cmd, req)
        try:
            try:
                handle(cmd, req)
            except Exception:
                log.exception("commande %s", cmd)
                publish(cmd, {"reqId": req, "status": "error", "error": "measure_failed"})
            try:
                after_command(cmd, started)
            except Exception:
                log.exception("fin de commande %s", cmd)
        finally:
            bt_release()
            forced_reach.discard(req)
        state["busyCmd"] = None


# ============================================================================ MQTT

def on_connect(c, userdata, flags, reason_code, properties=None):
    log.info("Connecté au broker %s:%s (%s)", MQTT_HOST, MQTT_PORT, reason_code)
    ready["at"] = now() + 3
    c.subscribe(f"{BASE}/cmd", qos=1)
    c.subscribe(f"{GW_BASE}/cmd", qos=1)
    c.subscribe(f"{BASE}/status", qos=1)   # une TV Android a-t-elle cette bague ?
    c.subscribe(f"{BASE}/location", qos=1) # localisation décidée par le serveur
    if RACE:
        c.subscribe(f"{BASE}/+", qos=1)    # résultats des autres gateways (ne pas refaire une mesure déjà faite)
    publish_status()                       # (statut de la gateway seulement pendant 3 s)

    def later():
        time.sleep(3.5)
        wan_ip(force=True)
        publish_status()
    threading.Thread(target=later, daemon=True).start()
    # Démarrage ou retour d'Internet : synchro vers le Client RHM (statut + batterie)
    jobs.put(("sync", None))


def system_cmd(cmd, req):
    """Redémarre le service (systemd le relance : Restart=always) ou la machine."""
    allowed = ALLOW_RESTART if cmd == "restart" else ALLOW_REBOOT
    ack = {"reqId": req, "gateway": GATEWAY, "ts": now()}
    if not allowed:
        client.publish(f"{GW_BASE}/{cmd}", json.dumps(dict(ack, status="error", error="not_allowed")), qos=1)
        return
    log.warning("%s demandé depuis l'admin (%s)", "Redémarrage du service" if cmd == "restart" else "Redémarrage de la machine", req)
    client.publish(f"{GW_BASE}/{cmd}", json.dumps(dict(ack, status="ok")), qos=1)
    # Statut « hors ligne » tout de suite (sinon l'admin attend la fin du keepalive)
    off = json.dumps({"online": False, "gateway": GATEWAY, "gatewayType": GATEWAY_TYPE, "ts": now()})
    client.publish(f"{GW_BASE}/status", off, qos=1, retain=True).wait_for_publish(3)
    time.sleep(1)
    if cmd == "reboot":
        subprocess.run(["systemctl", "reboot"], capture_output=True, timeout=20)
        time.sleep(30)
    else:
        # systemctl restart <service> (--no-block : systemd fait le redémarrage même si ce
        # programme est arrêté pendant la commande)
        try:
            r = subprocess.run(["systemctl", "--no-block", "restart", SERVICE_NAME],
                               capture_output=True, text=True, timeout=20)
            if r.returncode == 0:
                log.warning("systemctl restart %s lancé", SERVICE_NAME)
                time.sleep(30)   # systemd arrête ce programme pendant ce temps
            else:
                log.error("systemctl restart %s : %s", SERVICE_NAME, (r.stderr or r.stdout).strip())
        except (OSError, subprocess.TimeoutExpired) as e:
            log.error("systemctl restart %s impossible : %s", SERVICE_NAME, e)
    # Sans systemd (lancé à la main) : on s'arrête ; avec systemd, Restart=always relance
    client.disconnect()
    os._exit(0)


def on_message(c, userdata, msg):
    try:
        p = json.loads(msg.payload.decode("utf-8") or "{}")
    except ValueError:
        return
    if not isinstance(p, dict):
        return
    if msg.topic == f"{BASE}/status":
        on_ring_status(p, retained=bool(msg.retain))
        return
    if msg.topic == f"{BASE}/location":
        on_location(p)
        return
    if msg.topic.startswith(f"{BASE}/") and msg.topic != f"{BASE}/cmd":
        # Passage de main : annonce / résultat d'une autre gateway pour ce reqId
        other, req = p.get("gateway"), p.get("reqId")
        if other and other != GATEWAY and req:
            if msg.topic == f"{BASE}/race" and p.get("event") == "claim":
                claimed[req] = (other, now())
                if len(claimed) > 300:
                    for k in list(claimed)[:100]:
                        claimed.pop(k, None)
            elif p.get("status") == "ok" or p.get("error") == "ring_removed":
                done_by_other.append(req)
            elif p.get("status") == "error":
                failed_by_holder.append(req)   # échec de la titulaire : la main passe
        return
    cmd = str(p.get("cmd") or "").lower()
    if not cmd:
        return
    req = p.get("reqId") or f"lx-{uuid.uuid4().hex[:8]}"
    log.info("Commande reçue : %s (%s)", cmd, req)
    if MULTI and msg.topic == f"{GW_BASE}/cmd" and norm_mac(str(p.get("mac") or "")) != RING_MAC:
        # Multi-bagues : commandes de la gateway (redémarrages, ping…) → gateway_multi.py ;
        # mesures sur le topic gateway → seulement l'instance de la bague indiquée (« mac »)
        return
    if cmd in ("restart", "reboot", "btrestart"):
        # Seulement sur le topic de la gateway (admin), jamais via le topic de la bague
        if msg.topic != f"{GW_BASE}/cmd" or MULTI:
            return
        if cmd == "btrestart":
            jobs.put((cmd, req))   # après la mesure en cours (file d'attente)
        else:
            threading.Thread(target=system_cmd, args=(cmd, req), daemon=True).start()
        return
    # Commande reçue sur le topic de CETTE gateway (eis/colmi/gateway/<nom>/cmd) : elle lui est adressée
    if msg.topic == f"{GW_BASE}/cmd":
        mac = norm_mac(str(p.get("mac") or ""))
        if mac and mac != RING_MAC:
            log.info("Commande %s (%s) pour la bague %s : pas la nôtre → ignorée", cmd, req, mac)
            return
        p["gateway"] = GATEWAY
    # Commande adressée à une gateway précise (serveur) : seulement celle-là l'exécute
    target = p.get("gateway")
    if target and target != GATEWAY:
        log.info("Commande %s (%s) pour « %s » : ignorée ici", cmd, req, target)
        return
    if cmd == "cancel":
        # « Annuler la mesure » (Client RHM) : la mesure en cours s'arrête, celles en file sont retirées
        if target == GATEWAY or (not target and not not_mine()):
            cancel_measures(req)
        return
    if p.get("oneTry"):
        one_try.add(req)
    # Test de portée pendant que cette gateway travaille avec la bague (mesure, pas…) : la bague est
    # forcément ici (connectée, elle n'émet plus) → réponse immédiate, sans attendre la file
    if cmd == "reach" and state.get("busyCmd") and not standby():
        log.info("Portée (%s) : occupée avec la bague (%s) → bague ici", req, state["busyCmd"])
        publish("reach", {"reqId": req, "source": "mqtt", "status": "ok", "reachable": True,
                          "rssi": None, "busy": state["busyCmd"]})
        return
    # Multi-bagues : portée lue dans l'écoute passive, tout de suite (sans file d'attente)
    if MULTI and cmd == "reach" and p.get("force"):
        # Confirmation demandée par client_api : vrai test (test_reachable_v1.py), pas l'écoute passive
        forced_reach.add(req)
    elif MULTI and cmd == "reach" and not standby() and seen_reach(req):
        return
    # Mesure demandée pendant un test de portée : on arrête le script de portée (Bluetooth redémarré avant la mesure)
    if (cmd in SCRIPT_CMDS or cmd in REALTIME or cmd in BLE_CMDS) and proc.get("kind") == "reach" \
            and proc.get("p") is not None \
            and (target == GATEWAY or (not target and not not_mine())):
        log.info("Mesure %s demandée : arrêt du test de portée en cours", cmd)
        proc["preempted"] = True
        proc["restart_needed"] = True
        try:
            proc["p"].terminate()
        except Exception:
            pass
    # Sans destinataire (admin, bot…) : la gateway où la bague a été localisée
    if not target and cmd != "reach" and not_mine():
        log.info("Commande %s (%s) : bague localisée sur « %s » → ignorée ici", cmd, req, location["gateway"])
        return
    if cmd in SCRIPT_CMDS or cmd in REALTIME or cmd in BLE_CMDS:
        proc["ble_waiting"] = proc.get("ble_waiting", 0) + 1
    jobs.put((cmd, req))


def main():
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS)
    # Gateway coupée : message de dernière volonté (la bague garde son dernier état côté serveur)
    if not MULTI:   # multi-bagues : dernière volonté posée par gateway_multi.py
        client.will_set(f"{GW_BASE}/status", json.dumps({"online": False, "gateway": GATEWAY, "gatewayType": GATEWAY_TYPE, "ts": now()}), qos=1, retain=True)
    client.on_connect = on_connect
    client.on_message = on_message
    client.reconnect_delay_set(1, 30)
    client.connect_async(MQTT_HOST, MQTT_PORT, keepalive=30)
    client.loop_start()
    threading.Thread(target=worker, daemon=True).start()
    log.info("GATEWAY RHM Linux « %s » · bague %s · %s", GATEWAY, RING_MAC, CLI)
    # Bague « de confiance » pour BlueZ : reconnexions plus rapides et sans demande
    try:
        subprocess.run(["bluetoothctl", "trust", RING_MAC], capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        pass

    def on_stop(signum=None, frame=None):
        # Ctrl+C / systemctl stop ou restart : Bluetooth redémarré avant de quitter
        log.info("Arrêt de la gateway (%s)", "Ctrl+C" if signum == signal.SIGINT else "signal %s" % signum)
        if MULTI:
            # Bague retirée de cette gateway ou arrêt du superviseur : pas de redémarrage Bluetooth
            # (les autres bagues du boîtier l'utilisent)
            bt_release()
            os._exit(0)
        try:
            client.publish(f"{GW_BASE}/status", json.dumps({"online": False, "gateway": GATEWAY,
                           "gatewayType": GATEWAY_TYPE, "ts": now()}), qos=1, retain=True).wait_for_publish(2)
        except Exception:
            pass
        if BT_RESTART_AFTER_SUCCESS:
            restart_bluetooth("arrêt de la gateway")
        os._exit(0)
    signal.signal(signal.SIGTERM, on_stop)
    signal.signal(signal.SIGINT, on_stop)

    last_check = 0
    while True:
        time.sleep(STATUS_EVERY)
        # Bague joignable ? « info » de temps en temps, seulement si rien n'est en cours
        if owner["name"] and not standby():
            release(f"plus de statut de « {owner['name']} » depuis {OWNER_TIMEOUT} s")
        # Course : titulaire disparue (plus de statut) → on tente de reprendre la bague
        if RACE and not state["holder"] and not standby() and (not holder["name"] or now() - holder["ts"] >= RACE_TAKEOVER) \
                and jobs.empty() and state["measuring"] is None:
            holder.update(name=None, ts=0)
            jobs.put(("sync", None))
        # Multi-bagues : l'écoute passive remplace ce contrôle (sinon une connexion + un redémarrage
        # Bluetooth par bague toutes les N s : l'écoute s'arrête sans cesse et les bagues « disparaissent »)
        if CHECK_EVERY and not MULTI and not standby() and now() - last_check >= CHECK_EVERY and jobs.empty() \
                and state["measuring"] is None:
            last_check = now()
            jobs.put(("info-silent", None))
        if client.is_connected():
            wan_ip()   # relue au plus toutes les 30 min
            publish_status()


if __name__ == "__main__":
    main()
