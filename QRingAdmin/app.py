"""
QRing Admin — supervision des bagues QRing (app Android = gateway) via MQTT + PostgreSQL.

- Écoute eis/colmi/# : une ligne par bague, mise à jour en direct (Server-Sent Events)
- Mesures à distance, gateways (bind / unbind / scan / langue)
- Écrit les résultats dans PostgreSQL (base smart_ring de DANY) : historique, bot, Web App
- Telegram : affectations + droits, utilisateurs, appariements QR, sessions Web App
- Configuration : fichier .env (le même que DANY)
"""
import hashlib
import hmac
import json
import logging
import re
import os
import queue
import sys
import threading
import time
import uuid
from functools import wraps
from urllib.parse import parse_qsl
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------- .env
# Ordre : QRING_ENV_FILE, ./.env (dossier QRingAdmin), ../.env (projet DANY)
HERE = Path(__file__).resolve().parent
for candidate in [os.getenv("QRING_ENV_FILE"), HERE / ".env", HERE.parent / ".env"]:
    if candidate and Path(candidate).is_file():
        load_dotenv(candidate, override=False)

# ---------------------------------------------------------------------------- lecture tolérante du .env
# « 60, » ou « 60 # commentaire » dans le .env ne doivent pas empêcher le démarrage.
def _env_number(name, default, cast, pattern):
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return cast(default)
    m = re.search(pattern, raw)
    if m:
        if m.group(0) != raw.strip():
            logging.getLogger("env").warning("%s=%r dans le .env : valeur lue %s", name, raw, m.group(0))
        return cast(m.group(0))
    logging.getLogger("env").warning("%s=%r invalide dans le .env : valeur par défaut %s", name, raw, default)
    return cast(default)


def env_int(name, default):
    return _env_number(name, default, int, r"-?\d+")


def env_float(name, default):
    return _env_number(name, default, float, r"-?\d+(?:\.\d+)?")


import paho.mqtt.client as mqtt
import race  # noqa: E402
from flask import Flask, Response, jsonify, redirect, render_template, request, send_file, session, url_for  # noqa: E402

import clientdb  # noqa: E402
import dbq  # noqa: E402
import photos  # noqa: E402
import telegram_notify as tg  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("qring")

MQTT_HOST = os.getenv("MQTT_HOST", "51.83.40.138")
MQTT_PORT = env_int("MQTT_PORT", "1883")
MQTT_USER = os.getenv("MQTT_USER", "")
MQTT_PASS = os.getenv("MQTT_PASSWORD", os.getenv("MQTT_PASS", ""))
PREFIX = (os.getenv("MQTT_PREFIX") or os.getenv("MQTT_TOPIC", "eis/colmi/#")).replace("#", "").strip("/")
ADMIN_PASSWORD = os.getenv("QRING_ADMIN_PASSWORD") or os.getenv("ADMIN_PASSWORD") or "admin"
OFFLINE_AFTER = env_int("QRING_OFFLINE_AFTER", "150")
PORT = env_int("QRING_ADMIN_PORT", "5055")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
WEBAPP_MAX_AGE = max(300, env_int("TELEGRAM_WEBAPP_MAX_AGE_SECONDS", "86400"))
# Même réglage que le bouton État du bot Telegram
WEAR_CHECK_SECONDS = max(5, env_int("TELEGRAM_WEAR_CHECK_SECONDS", "15"))
WEAR_REUSE_SECONDS = max(0, env_int("TELEGRAM_WEAR_REUSE_SECONDS", "120"))

MEASURES = ["hr", "spo2", "temp", "bp", "hrv", "stress", "fatigue", "health", "all"]
SYNCS = ["steps", "sleep", "sedentary", "workouts", "history", "battery", "info"]
# métrique PostgreSQL ↔ type de l'app
DB_METRIC = {"hr": "heart_rate", "spo2": "spo2", "temp": "temperature", "bp": "blood_pressure",
             "hrv": "hrv", "stress": "stress", "fatigue": "fatigue", "health": "health_check",
             "steps": "steps", "battery": "battery"}
APP_TYPE = {v: k for k, v in DB_METRIC.items()}

app = Flask(__name__)
app.secret_key = os.getenv("QRING_SECRET_KEY") or os.getenv("SECRET_KEY") or ("qring-" + uuid.uuid4().hex)

# ---------------------------------------------------------------------------- état en mémoire

state_lock = threading.RLock()
rings = {}
gateways = {}
events = []
subscribers = []


def now():
    return int(time.time())


def tv_ts(v):
    """Heure envoyée par la Gateway RHM (secondes ou millisecondes) → secondes, 0 si absente."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 1e9:
        return 0
    return min(int(v / 1000 if v > 1e12 else v), now())



def mac_from_topic(t):
    t = t.upper()
    return ":".join(t[i:i + 2] for i in range(0, 12, 2)) if len(t) == 12 else t


def topic_mac(mac):
    return mac.replace(":", "").replace("-", "").upper()


def new_ring(mac):
    return {
        "mac": mac, "name": "", "model": "", "firmware": "", "gateway": "", "deviceName": "",
        "online": False, "ring": "unknown", "worn": None, "battery": None, "charging": False,
        "lanIp": None, "wanIp": None, "lang": None, "statusTs": 0, "measuring": None,
        "values": {}, "pending": {}, "errors": {}, "unbound": False, "inDb": False, "tgCount": 0,
        "multiGw": [],
    }


def new_gateway(name):
    return {"name": name, "deviceName": "", "ringMac": "", "online": False, "ring": "unknown", "lanIp": None,
            "wanIp": None, "lang": None, "statusTs": 0, "scan": None, "bind": None, "appVersion": "",
            "gatewayType": "android", "sys": None, "ringOwner": None}


def broadcast(kind, data):
    msg = json.dumps({"kind": kind, "data": data}, default=str)
    for q in list(subscribers):
        try:
            q.put_nowait(msg)
        except queue.Full:
            pass


def add_event(level, text, mac=None, gateway=None):
    ev = {"ts": now(), "level": level, "text": text, "mac": mac, "gateway": gateway}
    with state_lock:
        events.insert(0, ev)
        del events[300:]
    broadcast("event", ev)


def push_ring(mac):
    with state_lock:
        r = rings.get(mac)
        if r:
            broadcast("ring", r)


def push_gateway(name):
    with state_lock:
        g = gateways.get(name)
        if g:
            broadcast("gateway", g)


def seed_from_db():
    """Remplit le tableau avec les bagues connues de PostgreSQL (dernières valeurs)."""
    try:
        rows = dbq.load_rings()
    except Exception as e:
        log.warning("Chargement des bagues PostgreSQL impossible : %s", e)
        return
    with state_lock:
        for row in rows:
            mac = row["mac"].upper()
            r = rings.setdefault(mac, new_ring(mac))
            r.update({"name": row["name"] or r["name"], "dbName": row["name"], "model": row["model"] or r["model"],
                      "firmware": row["fw_version"] or r["firmware"], "gateway": row["gateway"] or r["gateway"],
                      "battery": row["battery"], "charging": bool(row["charging"]), "inDb": True,
                      "tgCount": int(row["tg_count"] or 0),
                      "worn": True if row["wear_status"] == "worn" else False if row["wear_status"] == "removed" else None,
                      "statusTs": int(row["last_seen"].timestamp()) if row["last_seen"] else 0})
            if row["battery"] is not None:
                r["battery"] = int(row["battery"])
            for m in row["latest"]:
                typ = APP_TYPE.get(m["metric"])
                if not typ:
                    continue
                data = {"value": m["value"]}
                if typ == "bp":
                    ex = m["extra"] or {}
                    data = {"sbp": ex.get("sbp", m["value"]), "dbp": ex.get("dbp")}
                if typ == "steps":
                    data = {"steps": int(m["value"] or 0)}
                r["values"][typ] = {"ts": int(m["time"].timestamp()), "data": data, "source": "db"}
    log.info("%d bague(s) chargée(s) depuis PostgreSQL", len(rows))


def refresh_tg_counts():
    try:
        counts = dbq.telegram_counts()
    except Exception:
        return
    with state_lock:
        for mac, r in rings.items():
            r["inDb"] = mac in counts
            r["tgCount"] = counts.get(mac, 0)
            broadcast("ring", r)


# ---------------------------------------------------------------------------- MQTT

ERROR_LABELS = {
    "ring_disconnected": "Hors portée", "ring_removed": "Bague retirée", "timeout": "Pas de résultat",
    "measure_failed": "Mesure échouée", "not_supported": "Non supporté", "busy": "Bague occupée",
    "invalid_value": "Valeur incohérente", "cancelled": "Annulée", "no_data": "Aucune donnée",
    "not_found": "Bague introuvable", "bluetooth_off": "Bluetooth désactivé",
    "bad_request": "Paramètre manquant", "unknown_command": "Commande inconnue",
}


# ---------------------------------------------------------------------------- réglages Client RHM (globaux)
SETTINGS_FILE = HERE / "admin_settings.json"
# Durée estimée de chaque mesure (s), affichée dans le Client RHM pendant la mesure (barre de progression).
# Réglable dans le .env : MEASURE_ESTIMATE_<MESURE>_SECONDS (ALL, HR, SPO2, TEMP, HRV, STRESS, FATIGUE, HEALTH,
# STEPS, BATTERY). « ALL » peut aussi être changé sur la page Gateways : cette valeur passe alors avant le .env.
_BUILTIN_SECONDS = {"all": 120, "hr": 40, "spo2": 40, "temp": 40, "hrv": 35, "stress": 30,
                    "fatigue": 30, "health": 30, "steps": 15, "battery": 10}


def _env_seconds(k, d):
    try:
        return max(5, min(600, int(str(os.getenv(f"MEASURE_ESTIMATE_{k.upper()}_SECONDS", d)).strip() or d)))
    except ValueError:
        return d


MEASURE_SECONDS_DEFAULT = {k: _env_seconds(k, v) for k, v in _BUILTIN_SECONDS.items()}
CLIENT_SETTINGS_DEFAULT = {"showGatewayType": True, "measureSeconds": MEASURE_SECONDS_DEFAULT}


def clean_seconds(d):
    """Valeurs changées sur la page de l'admin (seulement celles-là ; le reste vient du .env)."""
    out = {}
    for k, v in (d or {}).items():
        if k in MEASURE_SECONDS_DEFAULT:
            try:
                out[k] = max(5, min(600, int(v)))
            except (TypeError, ValueError):
                pass
    return out


def effective_seconds(overrides):
    return dict(MEASURE_SECONDS_DEFAULT, **(overrides or {}))


def load_client_settings():
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    # (ancien « measureSeconds » complet ignoré : il bloquait les valeurs du .env)
    ov = clean_seconds(data.get("measureOverrides"))
    return {"showGatewayType": bool(data.get("showGatewayType", True)),
            "measureOverrides": ov, "measureSeconds": effective_seconds(ov),
            # Bagues sur TV Android : boutons « Mesurer HR + SpO2 » et « Autres mesures » du Client RHM
            # (réglage global + exceptions par bague : true = afficher, false = masquer, absent = global)
            "tvShowAll": bool(data.get("tvShowAll", True)),
            "tvShowOther": bool(data.get("tvShowOther", True)),
            "tvButtons": clean_tv_buttons(data.get("tvButtons")),
            # Lecture du RSSI par la GATEWAY RHM Android, par bague (absent = oui)
            "rssiRead": {str(k).upper(): bool(v) for k, v in (data.get("rssiRead") or {}).items()}}


def clean_tv_buttons(d):
    out = {}
    for mac, v in (d or {}).items():
        if not isinstance(v, dict):
            continue
        e = {k: bool(v[k]) for k in ("all", "other") if v.get(k) is not None}
        if e:
            out[str(mac).upper()] = e
    return out


client_settings = load_client_settings()


def publish_client_settings():
    """Réglages lus par client_api.py (retenu sur le broker, republié à chaque démarrage de l'admin)."""
    mqttc.publish(f"{PREFIX}/config/client", json.dumps(client_settings), qos=1, retain=True)


def on_connect(client, userdata, flags, reason_code, properties=None):
    if reason_code == 0 or str(reason_code) == "Success":
        client.subscribe(f"{PREFIX}/#", qos=1)
        add_event("ok", f"Connecté au broker {MQTT_HOST}:{MQTT_PORT}")
        # Noms des bagues (base de données) pour les GATEWAY RHM
        threading.Thread(target=publish_profiles, daemon=True).start()
        publish_client_settings()
        zones_cache.pop("published", None)                       # (re)connexion : listes republiées
        threading.Thread(target=publish_photos, daemon=True).start()
        threading.Thread(target=load_zones, daemon=True).start()
    else:
        add_event("error", f"Connexion broker refusée : {reason_code}")
    broadcast("broker", {"online": True})


def on_disconnect(client, userdata, flags, reason_code, properties=None):
    add_event("error", "Déconnecté du broker, reconnexion…")
    broadcast("broker", {"online": False})


def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except Exception:
        return
    if not isinstance(payload, dict):
        return
    parts = msg.topic.split("/")
    base = PREFIX.split("/")
    if parts[: len(base)] != base:
        return
    rest = parts[len(base):]
    try:
        if len(rest) >= 3 and rest[0] == "gateway":
            handle_gateway(rest[1], rest[2], payload)
        elif len(rest) == 2 and len(rest[0]) == 12 and rest[1] == "location":
            mac = mac_from_topic(rest[0])
            with state_lock:
                r_ = rings.setdefault(mac, new_ring(mac))
                old = r_.get("location") or None
                r_["location"] = payload
            log_location_change(mac, old, payload)
            push_ring(mac)
        elif len(rest) == 2 and len(rest[0]) == 12 and rest[1] not in ("profile", "race"):
            # Format de l'app Android : eis/colmi/<MAC>/<type> (« profile » = nom publié par l'admin)
            handle_ring(mac_from_topic(rest[0]), rest[1], payload, f"{PREFIX}/{rest[0].upper()}")
    except Exception as e:
        log.exception("message %s", msg.topic)
        add_event("error", f"Message illisible sur {msg.topic} : {e}")


def log_location_change(mac, old, new):
    """Historique des déplacements (base) : seulement quand la pièce change, hors portée, retour."""
    if not isinstance(new, dict) or not isinstance(old, dict) or new.get("mode") == "scan":
        return      # premier message après démarrage (état inconnu avant) : rien à enregistrer
    was, now_ = bool(old.get("reachable")), bool(new.get("reachable"))
    gw, before = new.get("gateway"), old.get("seenGateway") or old.get("gateway")
    if now_ and not was:
        ev = "back"
    elif now_ and gw and before and gw != before:
        ev = "arrival"
    elif was and not now_:
        ev = "out_of_range"
    else:
        return
    dbq.enqueue("location", mac=mac, payload={"rssi": new.get("rssi"), "ts": new.get("ts")},
                gateway=gw if now_ else before, prev_gateway=before if ev == "arrival" else None, event=ev)


def handle_gateway(name, sub, p):
    if sub in ("cmd", "rings"):
        return
    if sub == "presence":
        # Écoute passive d'une gateway multi-bagues (toutes les ~5 s) : bagues entendues + RSSI
        with state_lock:
            g = gateways.setdefault(name, new_gateway(name))
            g["presence"] = {"ts": now(), "seen": p.get("seen") or {}, "rings": p.get("rings") or []}
            last = g.get("presencePush", 0)
            if now() - last < 15:
                return
            g["presencePush"] = now()
        push_gateway(name)
        return
    with state_lock:
        g = gateways.setdefault(name, new_gateway(name))
        if sub == "status":
            was = g["online"]
            g.update({"online": bool(p.get("online")), "ring": p.get("ring", "unknown"),
                      "ringMac": p.get("ringMac") or "", "deviceName": p.get("deviceName") or g["deviceName"],
                      "lanIp": p.get("lanIp"), "wanIp": p.get("wanIp"), "lang": p.get("lang"),
                      "appVersion": p.get("appVersion", "") or g["appVersion"], "statusTs": now(),
                      "ringOwner": p.get("ringOwner"), "ringOwnerType": p.get("ringOwnerType"),
                      "roaming": p.get("roaming"), "multi": bool(p.get("multi")),
                      "rings": p.get("rings") if isinstance(p.get("rings"), list) else None,
                      "busy": p.get("busy"), "scanner": p.get("scanner")})
            # Gateway Linux : type annoncé (.env GATEWAY_TYPE) + CPU / RAM / température / disque
            if "gatewayType" in p:
                g["gatewayType"] = str(p.get("gatewayType") or "android").lower()
            if g["online"]:
                g["sys"] = p.get("sys") if isinstance(p.get("sys"), dict) else None
            if g["online"] and not was:
                add_event("ok", f"Gateway {name} en ligne", gateway=name)
            elif not g["online"] and was:
                add_event("error", f"Gateway {name} hors ligne", gateway=name)
            dbq.enqueue("gateway_status", name=name, deviceName=g["deviceName"], appVersion=g["appVersion"])
            # Gateway Linux en veille (priorité Android) : elle n'a plus la bague
            if p.get("ring") == "standby" and p.get("ringMac"):
                rm = str(p["ringMac"]).upper()
                if rm in rings:
                    rings[rm].setdefault("gwSeen", {})[p.get("gateway") or name] = {"ts": now(), "online": True, "ring": "standby"}
        elif sub == "diag":
            # Gateway Android (QRingMqtt) : compteurs de stabilité toutes les 5 min
            prev = g.get("diag") or {}
            g["diag"] = dict(p, receivedTs=now())
            if (p.get("rescues") or 0) > (prev.get("rescues") or 0) and prev:
                add_event("warn", f"{name} : reconnexion de secours de la bague ({p.get('lastError') or 'SDK bloqué'})",
                          gateway=name)
        elif sub == "scan" and p.get("status") == "ok":
            g["scan"] = {"ts": now(), "rings": p.get("rings", [])}
            add_event("info", f"{name} : {p.get('count', 0)} bague(s) à proximité", gateway=name)
        elif sub == "bind":
            g["bind"] = {"ts": now(), "status": p.get("status"), "error": p.get("error"),
                         "mac": p.get("ringMac") or p.get("mac")}
            if p.get("status") == "ok":
                add_event("ok", f"{name} associé à la bague {p.get('ringMac')}", gateway=name, mac=p.get("ringMac"))
            elif p.get("status") == "error":
                add_event("error", f"{name} : association impossible ({ERROR_LABELS.get(p.get('error'), p.get('error'))})", gateway=name)
        elif sub == "unbind" and p.get("status") == "ok":
            add_event("warn", f"{name} : bague {p.get('ringMac')} dissociée", gateway=name, mac=p.get("ringMac"))
        elif sub == "btrestart":
            if p.get("status") == "running":
                add_event("info", f"{name} : redémarrage du Bluetooth…", gateway=name)
            elif p.get("status") == "ok":
                add_event("ok" if p.get("ringOk") else "warn",
                          f"{name} : Bluetooth redémarré · bague " + ("joignable" if p.get("ringOk") else "injoignable"), gateway=name)
            else:
                add_event("error", f"{name} : redémarrage Bluetooth impossible ({p.get('error')})", gateway=name)
        elif sub in ("restart", "reboot"):
            what = "service" if sub == "restart" else "machine"
            if p.get("status") == "ok":
                add_event("warn", f"{name} : redémarrage {what} en cours…", gateway=name)
            else:
                add_event("error", f"{name} : redémarrage {what} refusé ({p.get('error')})", gateway=name)
        elif sub == "lang" and p.get("status") == "ok":
            g["lang"] = p.get("lang")
            add_event("info", f"{name} : langue {p.get('lang')}", gateway=name)
    push_gateway(name)


GW_CONFLICT_SECONDS = 120


def multi_gateway(mac, p):
    """Même bague annoncée par plusieurs Gateway RHM : alerte + garde celle qui a vraiment la bague.
    True = statut à ignorer (une autre gateway a la bague « connectée »)."""
    gw = p.get("gateway")
    if not gw:
        return False
    t = now()
    with state_lock:
        r = rings.setdefault(mac, new_ring(mac))
        seen = r.setdefault("gwSeen", {})
        seen[gw] = {"ts": t, "online": bool(p.get("online")), "ring": p.get("ring")}
        live = {n: v for n, v in seen.items() if v["online"] and t - v["ts"] < GW_CONFLICT_SECONDS
                and v["ring"] not in (None, "unknown", "unbound", "no_ring", "standby")}
        multi = sorted(live) if len(live) > 1 else []
        # Alerte seulement si ça dure (≥ 90 s) : un passage Linux → TV normal dure quelques secondes
        if not multi:
            r["multiSince"], r["multiGw"] = 0, []
        else:
            r["multiSince"] = r.get("multiSince") or t
            if t - r["multiSince"] >= 90 and multi != r.get("multiGw"):
                r["multiGw"] = multi
                add_event("warn", f"{r['name'] or mac} annoncée par {len(multi)} Gateway RHM : {', '.join(multi)} "
                                  "— une seule doit avoir la bague (dissociez-la de l'autre)", mac, gw)
        holders = [n for n, v in live.items() if n != gw and v["ring"] == "connected"]
        return bool(holders) and p.get("ring") != "connected"


def handle_ring(mac, sub, p, base_topic):
    if sub == "cmd":
        # Commande publiée par un autre lanceur (bot Telegram…) : la bague devient occupée
        cmd = p.get("cmd")
        if cmd in MEASURES:
            with state_lock:
                r = rings.setdefault(mac, new_ring(mac))
                if cmd not in r["pending"]:
                    rid = str(p.get("reqId", ""))
                    src = "telegram" if rid.startswith("tg-") else "app" if rid.startswith("app-") else "mqtt"
                    r["pending"][cmd] = {"since": now(), "requested": now(), "reqId": p.get("reqId"),
                                         "source": src, "confirmed": False}
                    r["errors"].pop(cmd, None)
                    who = {"telegram": "Telegram", "app": "app QRingClient"}.get(src, "MQTT")
                    add_event("info", f"Commande {cmd.upper()} reçue ({who}) pour {r['name'] or mac}", mac)
            push_ring(mac)
        return
    if sub == "status" and multi_gateway(mac, p):
        push_ring(mac)
        return
    with state_lock:
        r = rings.setdefault(mac, new_ring(mac))
        worn_before = r["worn"]
        gw = p.get("gateway") or r["gateway"]
        r["gateway"] = gw
        if p.get("ringModel"):
            r["model"] = p["ringModel"]

        if sub == "status":
            was_online, was_worn, was_ring = r["online"], r["worn"], r["ring"]
            # Heures envoyées par la Gateway RHM (unboundAt / boundAt / removedAt, gardées même après
            # redémarrage) ; anciennes versions : « ts » du statut ou heure vue par ce service.
            ts = tv_ts(p.get("ts")) or now()
            if p.get("ring") == "unbound":
                if tv_ts(p.get("unboundAt")):
                    r["unboundTs"] = tv_ts(p.get("unboundAt"))
                elif was_ring != "unbound" or not r.get("unboundTs"):
                    r["unboundTs"] = ts
            else:
                if was_ring == "unbound" and p.get("ring") not in (None, "no_ring", "unknown"):
                    r["unboundTs"], r["boundTs"] = 0, ts
                if tv_ts(p.get("boundAt")):
                    r["boundTs"] = tv_ts(p.get("boundAt"))
            if "removedAt" in p:
                r["removedTsTv"] = tv_ts(p.get("removedAt"))
            if not p.get("online") and p.get("ring") in (None, "unknown") and r["statusTs"]:
                # Gateway RHM coupée (message de dernière volonté) : on garde le dernier état connu
                # de la bague et l'heure du dernier vrai statut
                p = dict(p, ring=r["ring"], worn=r["worn"], battery=r["battery"], charging=r["charging"],
                         measuring=None)
                keep_ts = r["statusTs"]
            else:
                keep_ts = None
            # Vrai nom Bluetooth de la bague (ex. « R10_6401 »), envoyé par la GATEWAY RHM
            if p.get("ringName") and p.get("ring") != "unbound":
                r["bleName"] = p["ringName"]
            r.update({
                "online": bool(p.get("online")), "ring": p.get("ring", r["ring"]),
                "name": r.get("dbName") or p.get("ringName") or r["name"], "firmware": p.get("firmware") or r["firmware"],
                "battery": p.get("battery", r["battery"]), "charging": bool(p.get("charging")),
                "worn": p.get("worn", r["worn"]), "measuring": p.get("measuring"),
                "deviceName": p.get("deviceName") or r["deviceName"], "lanIp": p.get("lanIp"),
                "wanIp": p.get("wanIp"), "lang": p.get("lang"), "statusTs": now(),
                "unbound": p.get("ring") == "unbound",
                "rssi": p.get("rssi") if p.get("ring") == "connected" else None,   # TV Android : signal (dBm)
            })
            if keep_ts:
                r["statusTs"] = keep_ts
            label = r["name"] or mac
            dbq.enqueue("ring_status", mac=mac, payload=p, gateway=gw, base_topic=base_topic)
            if r["unbound"] and was_ring != "unbound":
                add_event("warn", f"{label} dissociée de {gw}", mac, gw)
            elif r["online"] and not was_online:
                add_event("ok", f"{label} : Gateway RHM {gw} en ligne", mac, gw)
            elif not r["online"] and was_online:
                add_event("error", f"{label} : Gateway RHM {gw} hors ligne (éteinte ou sans internet)", mac, gw)
                dbq.enqueue("event", mac=mac, payload=p, gateway=gw, event_type="gateway_offline", severity="warning")
            if r["online"] and r["ring"] != was_ring and r["ring"] == "disconnected":
                add_event("error", f"{label} : hors portée (Bluetooth)", mac, gw)
                dbq.enqueue("event", mac=mac, payload=p, gateway=gw, event_type="out_of_zone",
                            severity="warning", reason="device_out_of_range")
            if r["online"] and r["ring"] == "connected" and was_ring in ("disconnected", "connecting"):
                add_event("ok", f"{label} : bague reconnectée", mac, gw)
                dbq.enqueue("event", mac=mac, payload=p, gateway=gw, event_type="back_online")
            if r["worn"] is False and was_worn is not False:
                add_event("warn", f"{label} : bague retirée", mac, gw)
                dbq.enqueue("event", mac=mac, payload=p, gateway=gw, event_type="ring_removed", severity="warning")
            elif r["worn"] is True and was_worn is False:
                dbq.enqueue("event", mac=mac, payload=p, gateway=gw, event_type="ring_worn")
        else:
            handle_result(r, mac, sub, p, gw, base_topic)
        # Heure du retrait : celle de la Gateway RHM si elle l'envoie, sinon vue par l'admin ;
        # effacée dès que la bague est de nouveau portée
        if r["worn"] is False:
            if r.get("removedTsTv"):
                r["removedTs"] = r["removedTsTv"]
            elif worn_before is not False:
                r["removedTs"] = now()
        else:
            r["removedTs"] = r["removedTsTv"] = 0
        # Heure de l'état : portée (dernière preuve) / hors portée (depuis)
        if r["worn"] is True and worn_before is not True:
            r["wornTs"] = now()
        if r["ring"] in ("disconnected", "connecting"):
            r["outTs"] = r.get("outTs") or now()
        elif r["ring"] == "connected":
            r["outTs"] = 0
    push_ring(mac)


def handle_result(r, mac, sub, p, gw, base_topic):
    st = p.get("status")
    if sub == "reach":
        # Tests de portée (localisation par client_api) : signal par gateway, sans événement ni base
        if st in ("ok", "error"):
            r.setdefault("reach", {})[gw] = {"ts": now(), "rssi": p.get("rssi") if st == "ok" else None,
                                             "reachable": st == "ok"}
        return
    # Roaming « course » (Gateway Linux) : erreur affichée seulement si toutes les gateways ont échoué
    if race.is_duplicate_ok(r, sub, p) or race.hold_error(r, sub, p, race.candidates(gateways, mac)):
        return
    if st in ("ok", "error"):
        race.settle(r, p)
    label = r["name"] or mac
    if st in ("measuring", "searching"):
        old = r["pending"].get(sub) or {}
        r["pending"][sub] = {"since": now(), "reqId": p.get("reqId") or old.get("reqId"),
                             "source": p.get("source") or old.get("source"), "confirmed": True,
                             "requested": old.get("requested") or old.get("since") or now()}
        r["errors"].pop(sub, None)
        return
    pnd = r["pending"].pop(sub, None) or {}
    ts = p.get("ts") or now()
    # Durée de la mesure : du « mesure en cours » confirmé par la TV jusqu'au résultat
    # Début : « mesure en cours » confirmé par la TV, sinon l'envoi de la commande
    started = pnd.get("since") or pnd.get("requested")
    dur = max(0, now() - started) if started else None
    p = dict(p, _started=started, _dur=dur)
    meta = {"reqId": p.get("reqId") or pnd.get("reqId"), "started": started, "dur": dur}
    # Lancée depuis Client RHM (reqId « app-<login>-… ») : origine « téléphone »
    req = meta["reqId"] or ""
    # « app-wissem-p123-spo2 » : 2e valeur d'une même connexion (script de mesure) → même demande
    req = re.sub(r"-(hr|spo2|temp|hrv|battery|bat|all|reach)$", "", req)
    meta["by"] = ("-".join(req.split("-")[1:-1]) if len(req.split("-")) >= 3 else "*") if req.startswith("app-") else ""
    # « r » = « Actualiser l'état », « p » = mesure lancée par un bouton
    meta["via"] = ("r" if req.rsplit("-", 1)[-1].startswith("r") else "p") if meta["by"] else ""
    src = "phone" if meta["by"] else p.get("source")
    if st == "ok":
        data = {k: v for k, v in p.items() if k not in (
            "reqId", "type", "status", "source", "ringMac", "ringModel", "gateway", "ts")}
        data = {k: v for k, v in data.items() if not k.startswith("_")}
        if sub == "sleep":
            # Nuits détaillées → base (ring_sleep_nights) ; en mémoire : seulement la dernière nuit
            data = {k: v for k, v in data.items() if k not in ("nights", "phases")}
        r["values"][sub] = dict(meta, ts=ts, data=data, source=src)
        r["errors"].pop(sub, None)
        if sub == "all":
            for k in ("hr", "spo2", "temp", "hrv", "stress"):
                if k in data:
                    r["values"][k] = dict(meta, ts=ts, data={"value": data[k]}, source=src)
            if "sbp" in data:
                r["values"]["bp"] = dict(meta, ts=ts, data={"sbp": data["sbp"], "dbp": data.get("dbp")}, source=src)
        if sub == "battery":
            r["battery"] = data.get("value", r["battery"])
            r["charging"] = bool(data.get("charging"))
        if sub in MEASURES:
            r["worn"] = True
            r["wornTs"] = max(r.get("wornTs") or 0, tv_ts(ts) or now())
            add_event("ok", f"{label} : {sub.upper()} = {short_value(sub, data)}", mac, gw)
        dbq.enqueue("result", mac=mac, sub=sub, payload=p, gateway=gw, base_topic=base_topic)
    elif st == "error":
        err = p.get("error", "error")
        r["errors"][sub] = dict(meta, ts=ts, code=err, label=ERROR_LABELS.get(err, err))
        if err == "ring_removed":
            r["worn"] = False
        level = "warn" if err in ("ring_removed", "cancelled", "busy") else "error"
        add_event(level, f"{label} : {sub.upper()} → {ERROR_LABELS.get(err, err)}", mac, gw)
        dbq.enqueue("result", mac=mac, sub=sub, payload=p, gateway=gw, base_topic=base_topic)


def short_value(sub, d):
    if sub == "bp":
        return f"{d.get('sbp')}/{d.get('dbp')} mmHg"
    if sub == "all":
        return " · ".join(f"{k} {d[k]}" for k in ("hr", "spo2", "temp") if k in d)
    unit = {"hr": " bpm", "spo2": " %", "temp": " °C", "hrv": " ms"}.get(sub, "")
    return f"{d.get('value')}{unit}"


mqttc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"qring-admin-{uuid.uuid4().hex[:8]}")


def publish_profile(mac, name):
    """Nom donné dans l'admin (« Mme Martin ») envoyé à la GATEWAY RHM : message retenu
    sur <prefix>/<MAC>/profile, reçu dès que la TV se (re)connecte."""
    # « rssi » : la GATEWAY RHM Android lit-elle la force du signal de la bague (oui par défaut) ?
    mqttc.publish(f"{PREFIX}/{topic_mac(mac)}/profile",
                  json.dumps({"name": name or "", "mac": mac.upper(), "ts": now(),
                              "rssi": rssi_enabled(mac)}, ensure_ascii=False),
                  qos=1, retain=True)


def rssi_enabled(mac):
    return (client_settings.get("rssiRead") or {}).get(mac.upper(), True) is not False


def publish_profiles(only_mac=None):
    """Nom de chaque bague pour les GATEWAY RHM (au démarrage, après un renommage ou un
    « Nom affiché ») : dernier « Nom affiché » des comptes, sinon nom de la bague."""
    try:
        names = dbq.display_names()
    except Exception as e:
        log.warning("Noms des bagues indisponibles : %s", e)
        return
    for mac, name in names.items():
        if only_mac is None or mac == only_mac.upper():
            publish_profile(mac, name)


def publish_cmd(topic, payload):
    info = mqttc.publish(topic, json.dumps(payload), qos=1)
    return info.rc == mqtt.MQTT_ERR_SUCCESS


def start_mqtt():
    mqttc.on_connect = on_connect
    mqttc.on_disconnect = on_disconnect
    mqttc.on_message = on_message
    if MQTT_USER:
        mqttc.username_pw_set(MQTT_USER, MQTT_PASS)
    mqttc.reconnect_delay_set(min_delay=1, max_delay=30)
    mqttc.connect_async(MQTT_HOST, MQTT_PORT, keepalive=30)
    mqttc.loop_start()


def watchdog():
    last_db = None
    while True:
        time.sleep(10)
        t = now()
        changed_r, changed_g = [], []
        with state_lock:
            for mac, r in rings.items():
                if r["online"] and r["statusTs"] and t - r["statusTs"] > OFFLINE_AFTER:
                    r["online"] = False
                    changed_r.append(mac)
                    add_event("error", f"{r['name'] or mac} : plus de nouvelles de {r['gateway']} depuis {OFFLINE_AFTER} s", mac, r["gateway"])
                for k, pnd in list(r["pending"].items()):
                    if t - pnd["since"] > 120:
                        r["pending"].pop(k, None)
                        changed_r.append(mac)
                # Course sans gagnante depuis 45 s : l'erreur est affichée
                for sub, last in race.expired(r):
                    handle_result(r, mac, sub, dict(last, roaming="final"), last.get("gateway") or r["gateway"],
                                  f"{PREFIX}/{topic_mac(mac)}")
                    changed_r.append(mac)
            for name, g in gateways.items():
                if g["online"] and g["statusTs"] and t - g["statusTs"] > OFFLINE_AFTER:
                    g["online"] = False
                    changed_g.append(name)
                    add_event("error", f"Gateway {name} : aucun statut depuis {OFFLINE_AFTER} s", gateway=name)
        for m in set(changed_r):
            push_ring(m)
        for n in changed_g:
            push_gateway(n)
        # état PostgreSQL + compteur d'appariements en attente
        s = dbq.status()
        try:
            s["pending_pairing"] = dbq.pairing_counts().get("pending", 0) if s["connected"] else 0
        except Exception:
            s["pending_pairing"] = 0
        sig = (s["connected"], s["write_errors"], s["pending_pairing"], s["allowed_measures_column"])
        if sig != last_db:
            if last_db is not None and last_db[0] != s["connected"]:
                add_event("ok" if s["connected"] else "error",
                          "PostgreSQL connecté" if s["connected"] else f"PostgreSQL non connecté : {s['last_error']}")
            last_db = sig
        broadcast("db", s)


# ---------------------------------------------------------------------------- web : sécurité

def login_required(f):
    @wraps(f)
    def w(*a, **k):
        if not session.get("ok"):
            if request.path.startswith("/api") or request.path == "/stream":
                return jsonify({"error": "auth"}), 401
            return redirect(url_for("login"))
        return f(*a, **k)
    return w


def ok(**kw):
    return jsonify(dict(ok=True, **kw))


def fail(msg, code=400, **kw):
    return jsonify(dict(ok=False, error=str(msg), **kw)), code


def serial(rows):
    """dict_row → JSON (dates en ISO)."""
    return json.loads(json.dumps(rows, default=lambda o: o.isoformat() if hasattr(o, "isoformat") else str(o)))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["ok"] = True
            return redirect(request.args.get("next") or url_for("index"))
        error = "Mot de passe incorrect"
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------- web : pages

@app.route("/")
@login_required
def index():
    return render_template("index.html", prefix=PREFIX, broker=f"{MQTT_HOST}:{MQTT_PORT}", start_view="rings",
                           weak_password=ADMIN_PASSWORD == "admin")


@app.route("/telegram/<view>")
@login_required
def telegram_view(view):
    views = {"pairing": "pairing", "users": "tgusers", "webapp": "webapp"}
    if view not in views:
        return redirect(url_for("index"))
    return render_template("index.html", prefix=PREFIX, broker=f"{MQTT_HOST}:{MQTT_PORT}", start_view=views[view],
                           weak_password=ADMIN_PASSWORD == "admin")


# ---------------------------------------------------------------------------- API : bagues / gateways

@app.route("/api/settings/client", methods=["POST"])
@login_required
def api_client_settings():
    body = request.get_json(force=True, silent=True) or {}
    if "showGatewayType" in body:
        client_settings["showGatewayType"] = bool(body["showGatewayType"])
    for k in ("tvShowAll", "tvShowOther"):
        if k in body:
            client_settings[k] = bool(body[k])
    if isinstance(body.get("measureSeconds"), dict):
        ov = dict(client_settings.get("measureOverrides") or {}, **clean_seconds(body["measureSeconds"]))
        # Même valeur que le .env : plus d'exception, le .env redevient la référence
        ov = {k: v for k, v in ov.items() if v != MEASURE_SECONDS_DEFAULT.get(k)}
        client_settings["measureOverrides"] = ov
        client_settings["measureSeconds"] = effective_seconds(ov)
    try:
        SETTINGS_FILE.write_text(json.dumps(client_settings, indent=2), encoding="utf-8")
    except OSError as e:
        return fail(f"Réglage non enregistré : {e}", 500)
    publish_client_settings()
    if "measureSeconds" in body:
        add_event("info", f"Client RHM : durée estimée « Tout mesurer » {client_settings['measureSeconds']['all']} s")
    elif "tvShowAll" in body or "tvShowOther" in body:
        add_event("info", "Client RHM (bagues Android) : « Mesurer HR + SpO2 » "
                  + ("affiché" if client_settings["tvShowAll"] else "masqué") + " · « Autres mesures » "
                  + ("affichées" if client_settings["tvShowOther"] else "masquées"))
    else:
        add_event("info", "Client RHM : type de Gateway " + ("affiché" if client_settings["showGatewayType"] else "masqué"))
    return ok(settings=client_settings)


@app.route("/api/ring/<mac>/rssi", methods=["POST"])
@login_required
def api_ring_rssi(mac):
    """La GATEWAY RHM Android lit-elle le RSSI de cette bague ? {"on": true|false}"""
    mac = mac.upper()
    on = bool((request.get_json(force=True, silent=True) or {}).get("on", True))
    rr = dict(client_settings.get("rssiRead") or {})
    if on:
        rr.pop(mac, None)          # oui = réglage par défaut
    else:
        rr[mac] = False
    client_settings["rssiRead"] = rr
    try:
        SETTINGS_FILE.write_text(json.dumps(client_settings, indent=2), encoding="utf-8")
    except OSError as e:
        return fail(f"Réglage non enregistré : {e}", 500)
    with state_lock:
        name = (rings.get(mac) or {}).get("name") or ""
    publish_profiles(only_mac=mac)
    if not name:
        publish_profile(mac, name)
    add_event("info", f"Bague {mac} : lecture du RSSI par la TV " + ("activée" if on else "désactivée"), mac=mac)
    return ok(on=on)


@app.route("/api/ring/<mac>/tvbuttons", methods=["POST"])
@login_required
def api_ring_tv_buttons(mac):
    """Exception par bague (TV Android) : {"all": true|false|null, "other": true|false|null} (null = global)."""
    mac = mac.upper()
    body = request.get_json(force=True, silent=True) or {}
    cur = dict(client_settings.get("tvButtons", {}).get(mac) or {})
    for k in ("all", "other"):
        if k in body:
            if body[k] is None:
                cur.pop(k, None)
            else:
                cur[k] = bool(body[k])
    tb = dict(client_settings.get("tvButtons") or {})
    if cur:
        tb[mac] = cur
    else:
        tb.pop(mac, None)
    client_settings["tvButtons"] = tb
    try:
        SETTINGS_FILE.write_text(json.dumps(client_settings, indent=2), encoding="utf-8")
    except OSError as e:
        return fail(f"Réglage non enregistré : {e}", 500)
    publish_client_settings()
    add_event("info", f"Client RHM : boutons de la bague {mac} (Android) : "
              + ", ".join(f"{'HR + SpO2' if k == 'all' else 'Autres mesures'} {'affiché' if v else 'masqué'}"
                          for k, v in cur.items()) if cur else f"Client RHM : bague {mac} → réglage global")
    return ok(tvButtons=cur)


# ------------------------------------------------------------------ zones (V2)
# Une zone = une Gateway RHM avec un nom de pièce ; chaque bague : 1 zone principale + 0 à 5 secondaires.
zones_cache = {"enabled": False, "rings": {}, "names": {}}


def load_zones():
    """Recharge les zones depuis PostgreSQL (si zones_migration.sql a été lancée)."""
    try:
        if not dbq.has_zones():
            zones_cache.update(enabled=False, rings={}, names={})
            return zones_cache
        names = {z["gateway"]: z["zone_label"] or "" for z in dbq.list_zones()}
        zones_cache.update(enabled=True, rings=dbq.all_ring_zones(), names=names)
        publish_gateway_rings()
    except Exception as e:
        log.warning("Zones non chargées : %s", e)
    return zones_cache


def zones_public():
    return {k: v for k, v in zones_cache.items() if k != "published"}


def publish_gateway_rings():
    """Liste des bagues de chaque Gateway RHM (zones principale + secondaires), retenue sur
    eis/colmi/gateway/<nom>/rings : gateway_multi.py écoute et mesure ces bagues."""
    if not zones_cache.get("enabled") or not mqttc.is_connected():
        return
    per_gw = {name: [] for name in zones_cache.get("names", {})}
    for mac, z in (zones_cache.get("rings") or {}).items():
        if z.get("main"):
            per_gw.setdefault(z["main"], []).append({"mac": mac, "role": "main"})
        for gw in z.get("secondary") or []:
            per_gw.setdefault(gw, []).append({"mac": mac, "role": "secondary"})
    # Noms des pièces + zones de chaque bague, pour le Client RHM (« Chambre 12 », « Dernière zone : Salon »)
    cfg = {"names": {k: v for k, v in (zones_cache.get("names") or {}).items() if v},
           "rings": zones_cache.get("rings") or {}}
    if zones_cache.setdefault("published", {}).get("__config__") != cfg:
        mqttc.publish(f"{PREFIX}/config/zones", json.dumps(dict(cfg, ts=now())), qos=1, retain=True)
        zones_cache["published"]["__config__"] = cfg
    for gw, lst in per_gw.items():
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", gw)
        lst = sorted(lst, key=lambda x: x["mac"])
        if zones_cache.setdefault("published", {}).get(gw) != lst:   # seulement si la liste a changé
            mqttc.publish(f"{PREFIX}/gateway/{safe}/rings",
                          json.dumps({"gateway": gw, "rings": lst, "ts": now()}), qos=1, retain=True)
            zones_cache["published"][gw] = lst


def zone_choices():
    """Gateways proposées comme zones : celles connues en base + celles vues sur MQTT."""
    out = {}
    try:
        for z in dbq.list_zones():
            out[z["gateway"]] = {"gateway": z["gateway"], "zone": z["zone_label"] or "",
                                 "type": z["gateway_type"], "online": False}
    except Exception:
        pass
    with state_lock:
        for g in gateways.values():
            e = out.setdefault(g["name"], {"gateway": g["name"], "zone": "", "type": None})
            e["online"] = bool(g.get("online"))
            e["type"] = e["type"] or g.get("gatewayType")
    return sorted(out.values(), key=lambda z: ((z["zone"] or z["gateway"]).lower()))


@app.route("/api/zones")
@login_required
def api_zones():
    if not load_zones()["enabled"]:
        return fail("Zones non installées : lancez zones_migration.sql sur la base", 503)
    return ok(zones=zone_choices(), max_secondary=dbq.MAX_SECONDARY_ZONES)


@app.route("/api/gateway/<name>/zone", methods=["POST"])
@login_required
def api_gateway_zone(name):
    """Nom de la pièce de la gateway (« Chambre 12 »)."""
    zone = ((request.get_json(force=True, silent=True) or {}).get("zone") or "").strip()
    if len(zone) > 60:
        return fail("Nom de pièce trop long (60 caractères max.)")
    with state_lock:
        gtype = (gateways.get(name) or {}).get("gatewayType")
    try:
        dbq.set_gateway_zone(name, zone, gtype if gtype in ("linux", "android") else None)
    except Exception as e:
        return fail(f"Base indisponible : {e}", 503)
    load_zones()
    broadcast("zones", zones_public())
    add_event("info", f"Gateway {name} : pièce « {zone or '—'} »", gateway=name)
    return ok(zone=zone)


@app.route("/api/ring/<mac>/zones", methods=["GET", "POST"])
@login_required
def api_ring_zones(mac):
    mac = mac.upper()
    if not load_zones()["enabled"]:
        return fail("Zones non installées : lancez zones_migration.sql sur la base", 503)
    if request.method == "GET":
        try:
            return ok(zones=dbq.ring_zones(mac), max_secondary=dbq.MAX_SECONDARY_ZONES)
        except Exception as e:
            return fail(f"Base indisponible : {e}", 503)
    body = request.get_json(force=True, silent=True) or {}
    main_gw = (body.get("main") or "").strip()
    secondary = [str(x).strip() for x in (body.get("secondary") or []) if str(x).strip()]
    known = {z["gateway"] for z in zone_choices()}
    unknown = [n for n in [main_gw] + secondary if n and n not in known]
    if unknown:
        return fail(f"Gateway inconnue : {unknown[0]}")
    try:
        dbq.ensure_gateways([main_gw] + secondary)
        zones = dbq.set_ring_zones(mac, main_gw, secondary)
    except ValueError as e:
        return fail(str(e).capitalize())
    except Exception as e:
        return fail(f"Base indisponible : {e}", 503)
    load_zones()
    broadcast("zones", zones_public())
    label = lambda z: z["zone"] or z["gateway"]
    add_event("info", f"Zones de {mac} : principale « {label(zones['main'])} »"
              + (" · secondaires " + ", ".join(f"« {label(z)} »" for z in zones["secondary"]) if zones["secondary"] else ""), mac)
    return ok(zones=zones)


# ------------------------------------------------------------------ photo du résident
def publish_photos():
    """Versions des photos (retenu) : le Client RHM recharge la photo d'une bague dès qu'elle change."""
    if mqttc.is_connected():
        mqttc.publish(f"{PREFIX}/config/photos", json.dumps({"photos": photos.versions(), "ts": now()}),
                      qos=1, retain=True)


@app.route("/api/ring/<mac>/photo", methods=["GET", "POST", "DELETE"])
@login_required
def api_ring_photo(mac):
    mac = mac.upper()
    if request.method == "GET":
        try:
            p = photos.path_for(mac)
        except ValueError:
            return fail("MAC invalide")
        if not os.path.exists(p):
            return fail("Pas de photo", 404)
        return send_file(p, mimetype="image/jpeg", max_age=0)
    if request.method == "DELETE":
        photos.delete(mac)
        v = None
    else:
        f = request.files.get("photo")
        try:
            v = photos.save(mac, f.read() if f else b"")
        except ValueError as e:
            return fail(str(e))
    with state_lock:
        r = rings.get(mac)
        if r:
            r["photoV"] = v
        label = (r and r.get("name")) or mac
    publish_photos()
    push_ring(mac)
    add_event("info", f"Photo du résident {'mise à jour' if v else 'supprimée'} : {label}", mac)
    return ok(photoV=v)


@app.route("/api/state")
@login_required
def api_state():
    s = dbq.status()
    pv = photos.versions()
    with state_lock:
        for m_, r_ in rings.items():
            r_["photoV"] = pv.get(m_.upper())
        return jsonify({"rings": list(rings.values()), "gateways": list(gateways.values()),
                        "clientSettings": client_settings,
                        "zones": zones_public(),
                        "events": events[:150], "broker": mqttc.is_connected(), "now": now(), "db": s,
                        "measureKeys": dbq.MEASURE_KEYS})


def send_ring_cmd(mac, cmd, body=None, source="admin", who=None):
    """Envoie une commande à la TV de la bague. Retourne (réponse dict, code HTTP).
    Règle : une seule mesure à la fois par bague (même mesure = partagée, autre = refusée)."""
    body = body or {}
    if cmd not in MEASURES + SYNCS + ["cancel", "ping"]:
        return {"ok": False, "error": "commande inconnue"}, 400
    # Verrou tenu pendant tout l'envoi : deux clics simultanés (admin + bot) ne peuvent pas lancer deux mesures
    with state_lock:
        r = rings.get(mac)
        if r and cmd in MEASURES:
            running = [k for k in r["pending"] if k in MEASURES]
            if running and cmd not in running:
                return {"ok": False, "error": f"Mesure {running[0].upper()} déjà en cours sur cette bague",
                        "busy": running[0]}, 409
            if cmd in running:
                return {"ok": True, "already": True, "reqId": r["pending"][cmd].get("reqId")}, 200
        req = {"telegram": "tg-", "webapp": "web-"}.get(source, "adm-") + uuid.uuid4().hex[:8]
        payload = {"cmd": cmd, "reqId": req}
        if "day" in body:
            payload["day"] = int(body["day"])
        sent = publish_cmd(f"{PREFIX}/{topic_mac(mac)}/cmd", payload)
        label = (r and r["name"]) or mac
        if r and cmd in MEASURES + SYNCS:
            r["pending"][cmd] = {"since": now(), "requested": now(), "reqId": req, "source": source, "confirmed": False}
            r["errors"].pop(cmd, None)
    push_ring(mac)
    add_event("info", f"Commande {cmd.upper()} envoyée à {label}" + (f" (Telegram : {who})" if who else ""), mac)
    return {"ok": True, "sent": sent, "reqId": req}, 200


@app.route("/api/ring/<mac>/cmd", methods=["POST"])
@login_required
def api_ring_cmd(mac):
    body = request.get_json(force=True, silent=True) or {}
    res, code = send_ring_cmd(mac, body.get("cmd"), body, "admin")
    return jsonify(res), code


@app.route("/api/ring/<mac>/sleep")
@login_required
def api_ring_sleep(mac):
    """Historique du sommeil : une ligne par nuit (30 derniers jours par défaut)."""
    try:
        days = min(max(int(request.args.get("days", "30")), 1), 365)
    except ValueError:
        days = 30
    try:
        return jsonify({"ok": True, "nights": dbq.sleep_nights(mac.upper(), days), "days": days})
    except Exception as e:
        return jsonify({"ok": False, "error": f"Base indisponible : {e}", "nights": []}), 503


@app.route("/api/rings", methods=["POST"])
@login_required
def api_add_ring():
    """« ➕ Ajouter une bague » : MAC + nom du résident (+ zone principale facultative).
    Les Gateway RHM Linux de ses zones la reçoivent ensuite d'elles-mêmes (pas de .env à modifier)."""
    body = request.get_json(force=True, silent=True) or {}
    h = re.sub(r"[^0-9A-Fa-f]", "", str(body.get("mac") or "")).upper()
    if len(h) != 12 or h in ("000000000000", "FFFFFFFFFFFF"):
        return fail("Adresse MAC invalide (ex. 30:32:42:32:64:01)")
    mac = ":".join(h[i:i + 2] for i in range(0, 12, 2))
    name = (body.get("name") or "").strip()
    if len(name) > 60:
        return fail("Nom trop long (60 caractères max.)")
    main_gw = (body.get("main") or "").strip()
    try:
        created, db_name = dbq.add_ring(mac, name or None)
    except Exception as e:
        return fail(f"Base indisponible : {e}", 503)
    with state_lock:
        r = rings.setdefault(mac, new_ring(mac))
        r["name"] = r["dbName"] = db_name
        r["inDb"] = True
    zones = None
    if main_gw:
        try:
            dbq.ensure_gateways([main_gw])
            zones = dbq.set_ring_zones(mac, main_gw, [])
            load_zones()
            broadcast("zones", zones_public())
        except ValueError as e:
            return fail(f"Bague {'ajoutée' if created else 'déjà connue'}, mais zone refusée : {e}")
        except Exception as e:
            return fail(f"Zone non enregistrée : {e}", 503)
    push_ring(mac)
    publish_profiles(mac)
    add_event("ok" if created else "info",
              f"Bague {mac} {'ajoutée' if created else 'déjà connue'} · « {db_name} »"
              + (f" · zone principale « {zones['main']['zone']} »" if zones and zones.get("main") else ""), mac)
    return ok(mac=mac, created=created, name=db_name, zones=zones)


@app.route("/api/ring/<mac>/name", methods=["POST"])
@login_required
def api_ring_name(mac):
    """Renommer la bague (ex. « Mme Martin ») : enregistré en base, vaut pour tous les comptes
    Client RHM qui n'ont pas de nom propre (« Bagues et droits »)."""
    mac = mac.upper()
    name = ((request.get_json(force=True, silent=True) or {}).get("name") or "").strip()
    if not name or len(name) > 60:
        return jsonify({"ok": False, "error": "Nom vide ou trop long (60 caractères max.)"}), 400
    try:
        if not dbq.rename_ring(mac, name):
            return jsonify({"ok": False, "error": "Bague inconnue en base"}), 404
    except Exception as e:
        return jsonify({"ok": False, "error": f"Base indisponible : {e}"}), 503
    with state_lock:
        r = rings.get(mac)
        if r:
            r["name"] = r["dbName"] = name
    add_event("info", f"Bague {mac} renommée « {name} »", mac)
    publish_profiles(mac)  # la GATEWAY RHM affiche le nouveau nom tout de suite
    push_ring(mac)
    return jsonify({"ok": True, "name": name})


@app.route("/api/gateway/<name>/cmd", methods=["POST"])
@login_required
def api_gateway_cmd(name):
    body = request.get_json(force=True, silent=True) or {}
    cmd = body.get("cmd")
    if cmd not in ("bind", "unbind", "scan", "lang", "ping", "restart", "reboot", "btrestart"):
        return fail("commande inconnue")
    if cmd in ("restart", "reboot", "btrestart"):
        with state_lock:
            g = gateways.get(name) or {}
        if g.get("gatewayType") != "linux":
            return fail("Redémarrage à distance disponible seulement pour une Gateway RHM Linux")
        if not g.get("online"):
            return fail("Gateway hors ligne")
    payload = {"cmd": cmd, "reqId": "adm-" + uuid.uuid4().hex[:8]}
    if cmd == "bind":
        mac = (body.get("mac") or "").strip()
        if len([c for c in mac if c.isalnum()]) != 12:
            return fail("MAC invalide")
        payload["mac"] = mac
    if cmd == "lang":
        if body.get("value") not in ("fr", "en", "ar"):
            return fail("langue invalide")
        payload["value"] = body["value"]
    sent = publish_cmd(f"{PREFIX}/gateway/{name}/cmd", payload)
    add_event("info", f"Commande {cmd} envoyée au gateway {name}", gateway=name)
    return ok(sent=sent, reqId=payload["reqId"])


@app.route("/api/gateway/<name>", methods=["DELETE"])
@login_required
def api_gateway_delete(name):
    """Supprime une Gateway RHM de la liste : retire son statut retenu du broker (sinon elle
    revient au prochain démarrage). PostgreSQL n'est pas modifié (l'historique reste lié)."""
    with state_lock:
        g = gateways.get(name)
        if not g:
            return fail("Gateway inconnue", 404)
        if g["online"]:
            return fail("Gateway en ligne : éteignez-la (ou arrêtez le service) avant de la supprimer, "
                        "sinon elle réapparaît à son prochain statut", 409)
        gateways.pop(name, None)
    # Message vide + retain = efface le statut retenu sur le broker
    mqttc.publish(f"{PREFIX}/gateway/{name}/status", b"", qos=1, retain=True)
    add_event("warn", f"Gateway {name} supprimée de la liste", gateway=name)
    broadcast("gateway_removed", {"name": name})
    return ok()


@app.route("/api/ring/<mac>/history")
@login_required
def api_history(mac):
    typ = request.args.get("type", "hr")
    metric = DB_METRIC.get(typ, "heart_rate" if typ == "all" else typ)
    try:
        rows = dbq.history(mac, metric, min(int(request.args.get("limit", "300")), 2000))
    except Exception as e:
        return fail(f"PostgreSQL : {e}", 503)
    out = []
    for x in rows:
        ex = x["extra"] or {}
        data = {"value": x["value"]}
        if typ == "bp":
            data = {"sbp": ex.get("sbp", x["value"]), "dbp": ex.get("dbp")}
        out.append({"ts": int(x["time"].timestamp()), "gateway": x["gateway"], "data": data,
                    "status": "ok" if x["status"] == "ok" else "error",
                    "error": None if x["status"] == "ok" else (x["reason"] or x["status"]), "reqId": ex.get("reqId"), "samples": x["samples"], "dur": ex.get("duration_s")})
    return jsonify(out)


@app.route("/api/ring/<mac>", methods=["DELETE"])
@login_required
def api_forget(mac):
    """Retire la bague du tableau (PostgreSQL n'est pas modifié)."""
    with state_lock:
        rings.pop(mac, None)
    broadcast("ring_removed_from_list", {"mac": mac})
    return ok()


@app.route("/api/db/status")
@login_required
def api_db_status():
    dbq.test()
    s = dbq.status()
    try:
        s["pending_pairing"] = dbq.pairing_counts().get("pending", 0)
    except Exception:
        s["pending_pairing"] = 0
    return ok(db=s)


# ---------------------------------------------------------------------------- API : Telegram

@app.route("/api/telegram/ring/<mac>", methods=["GET", "POST"])
@login_required
def api_tg_ring(mac):
    try:
        if request.method == "GET":
            ring, rows = dbq.list_access(mac)
            if not ring:
                return fail("Bague absente de PostgreSQL : elle apparaîtra dès sa première mesure enregistrée.", 404)
            users = [u for u in dbq.list_users() if u["active"]]
            return ok(ring=serial(ring), access=serial(rows), users=serial(users),
                      allowedMeasures=dbq.has_allowed_measures(), measureKeys=dbq.MEASURE_KEYS)

        data = request.get_json(silent=True) or {}
        access_id, was_active, now_active = dbq.upsert_access(mac, data)
        sent, err = False, None
        ring, rows = dbq.list_access(mac)
        user = next((r for r in rows if int(r["telegram_user_id"]) == int(data.get("telegram_user_id"))), None)
        # Message seulement lors d'une (ré)affectation ou d'une désactivation, pas d'un simple changement de droits
        if user and now_active and not was_active:
            sent, err = tg.ring_assigned(user, ring)
        elif user and was_active and not now_active:
            sent, err = tg.ring_unassigned(user, ring)
        who = user and (user["firstname"] or user["pseudo"] or user["id_telegram"])
        add_event("info", f"Telegram : droits de {who} sur {ring['name']} enregistrés"
                  + (" · message envoyé" if sent else f" · message non envoyé ({err})" if err else ""), mac.upper())
        refresh_tg_counts()
        return ok(access_id=access_id, notification_sent=sent, notification_error=err)
    except (LookupError, ValueError) as e:
        return fail(e)
    except Exception as e:
        log.exception("telegram ring")
        return fail(e, 500)


@app.route("/api/telegram/ring/<mac>/<int:access_id>", methods=["DELETE"])
@login_required
def api_tg_ring_delete(mac, access_id):
    try:
        ring, rows = dbq.list_access(mac)
        user = next((r for r in rows if int(r["access_id"]) == access_id), None)
        deleted = dbq.delete_access(mac, access_id)
        sent, err = False, None
        if deleted and ring and user and user["active"]:
            sent, err = tg.ring_unassigned(user, ring)
        who = user and (user["firstname"] or user["pseudo"] or user["id_telegram"])
        add_event("warn", f"Telegram : {who} retiré de {ring and ring['name']}"
                  + (" · message envoyé" if sent else f" · message non envoyé ({err})" if err else ""), mac.upper())
        refresh_tg_counts()
        return ok(deleted=deleted, notification_sent=sent, notification_error=err)
    except Exception as e:
        return fail(e)


@app.route("/api/telegram/users")
@login_required
def api_tg_users():
    try:
        return ok(users=serial(dbq.list_users()))
    except Exception as e:
        return fail(e, 503)


@app.route("/api/telegram/users/<int:user_id>/active", methods=["POST"])
@login_required
def api_tg_user_active(user_id):
    try:
        row = dbq.set_user_active(user_id, bool((request.get_json(silent=True) or {}).get("active")))
        if not row:
            return fail("Utilisateur introuvable", 404)
        add_event("info", f"Telegram : compte {row['firstname'] or row['pseudo'] or row['id_telegram']} "
                  + ("activé" if row["active"] else "désactivé"))
        return ok(user=serial(row))
    except Exception as e:
        return fail(e)


@app.route("/api/telegram/pairing")
@login_required
def api_tg_pairing():
    try:
        st = request.args.get("status", "pending")
        return ok(requests=serial(dbq.list_pairing(None if st == "all" else st)), counts=dbq.pairing_counts())
    except Exception as e:
        return fail(e, 503)


@app.route("/api/telegram/pairing/<int:request_id>/<action>", methods=["POST"])
@login_required
def api_tg_pairing_decide(request_id, action):
    if action not in ("approve", "reject"):
        return fail("action invalide")
    try:
        row = dbq.approve_pairing(request_id) if action == "approve" else dbq.reject_pairing(request_id)
        if not row:
            return fail("Demande introuvable", 404)
        if row.get("result") == "already_decided":
            return fail("Demande déjà traitée", 409, status=row.get("status"))
        if action == "approve":
            sent, err = tg.ring_assigned(
                {"id_telegram": row["id_telegram"], "firstname": row["firstname"]},
                {"id": row["ring_id"], "name": row["ring_name"], "mac": row["mac"]})
        else:
            sent, err = tg.pairing_rejected(row)
        who = row["firstname"] or row["pseudo"] or row["id_telegram"]
        add_event("ok" if action == "approve" else "warn",
                  f"Appariement {'approuvé' if action == 'approve' else 'refusé'} : {who} → {row['ring_name']}"
                  + (" · message envoyé" if sent else f" · message non envoyé ({err})"), row["mac"].upper())
        refresh_tg_counts()
        return ok(status=row["status"], notification_sent=sent, notification_error=err)
    except Exception as e:
        return fail(e)


@app.route("/api/telegram/webapp")
@login_required
def api_tg_webapp():
    try:
        return ok(sessions=serial(dbq.list_webapp_sessions()), stats=serial(dbq.webapp_stats()),
                  activeSeconds=dbq.WEBAPP_ACTIVE_SECONDS)
    except Exception as e:
        return fail(e, 503)


# ---------------------------------------------------------------------------- Comptes de l'app QRingClient
# L'app téléphone passe par client_api.py (service séparé). Ici : création des comptes et affectation des bagues.

@app.route("/clients")
@login_required
def clients_page():
    return render_template("clients.html", measures=clientdb.CLIENT_MEASURES)


@app.get("/api/clients")
@login_required
def api_clients():
    if not clientdb.tables_ready():
        return fail("Tables absentes : lancez client_migration.sql sur la base", 503, migration=True)
    try:
        return ok(users=serial(clientdb.list_users()), rings=serial(clientdb.all_rings()),
                  measures=clientdb.CLIENT_MEASURES)
    except Exception as e:
        return fail(e, 503)


@app.post("/api/clients")
@login_required
def api_client_create():
    body = request.get_json(silent=True) or {}
    try:
        u = clientdb.create_user(body.get("login"), body.get("password"), body.get("display_name"), body.get("lang", "fr"))
    except ValueError as e:
        return fail(e)
    except Exception as e:
        return fail(e, 503)
    add_event("info", f"App QRingClient : compte « {u['login']} » créé")
    return ok(user=serial(u))


@app.post("/api/clients/<int:user_id>")
@login_required
def api_client_update(user_id):
    body = request.get_json(silent=True) or {}
    try:
        u = clientdb.update_user(user_id, body)
    except ValueError as e:
        return fail(e)
    except Exception as e:
        return fail(e, 503)
    if not u:
        return fail("Compte introuvable", 404)
    what = "mot de passe changé" if body.get("password") else ("activé" if body.get("active") else "désactivé") \
        if "active" in body else "modifié"
    add_event("info", f"App QRingClient : compte « {u['login']} » {what}")
    return ok(user=serial(u))


@app.delete("/api/clients/<int:user_id>")
@login_required
def api_client_delete(user_id):
    try:
        u = clientdb.get_user(user_id)
        deleted = clientdb.delete_user(user_id)
    except Exception as e:
        return fail(e, 503)
    if deleted and u:
        add_event("warn", f"App QRingClient : compte « {u['login']} » supprimé")
    return ok(deleted=deleted)


@app.get("/api/clients/<int:user_id>/access")
@login_required
def api_client_access(user_id):
    try:
        return ok(user=serial(clientdb.get_user(user_id)), access=serial(clientdb.list_access(user_id)),
                  rings=serial(clientdb.all_rings()), measures=clientdb.CLIENT_MEASURES)
    except Exception as e:
        return fail(e, 503)


@app.post("/api/clients/<int:user_id>/access")
@login_required
def api_client_access_save(user_id):
    try:
        access_id = clientdb.upsert_access(user_id, request.get_json(silent=True) or {})
    except ValueError as e:
        return fail(e)
    except Exception as e:
        return fail(e, 503)
    # « Nom affiché » (ex. « Mme Martin ») → GATEWAY RHM mise à jour tout de suite
    threading.Thread(target=publish_profiles, daemon=True).start()
    return ok(access_id=access_id)


@app.delete("/api/clients/<int:user_id>/access/<int:access_id>")
@login_required
def api_client_access_delete(user_id, access_id):
    try:
        return ok(deleted=clientdb.delete_access(user_id, access_id))
    except Exception as e:
        return fail(e, 503)


# ---------------------------------------------------------------------------- Web App Telegram (Mini App)
# /webapp/ring/<mac> : une page par bague. L'utilisateur ne voit QUE cette bague, et seulement
# s'il y est affecté (droit « voir »). Identité prouvée par initData signé par Telegram
# (jamais initDataUnsafe). Chaque appel relit les droits en base.

WEBAPP_MEASURES = ["hr", "spo2", "hrv", "temp"]
WEBAPP_LIMITS = {"hr": 60, "spo2": 90, "hrv": 90, "temp": 90}


def mac_from_key(key):
    k = re.sub(r"[^0-9a-fA-F]", "", str(key or "")).upper()
    return ":".join(k[i:i + 2] for i in range(0, 12, 2)) if len(k) == 12 else None


def validate_init_data(init_data):
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN absent du .env")
    pairs = dict(parse_qsl(str(init_data or ""), keep_blank_values=True))
    received = pairs.pop("hash", None)
    if not received:
        raise PermissionError("Ouvrez cette page depuis le bot Telegram")
    check = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret = hmac.new(b"WebAppData", TELEGRAM_BOT_TOKEN.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(hmac.new(secret, check.encode(), hashlib.sha256).hexdigest(), received):
        raise PermissionError("Signature Telegram invalide")
    auth = int(pairs.get("auth_date") or 0)
    if auth <= 0 or now() - auth > WEBAPP_MAX_AGE or auth - now() > 60:
        raise PermissionError("Session Telegram expirée, rouvrez depuis le bot")
    user = json.loads(pairs.get("user") or "{}")
    if not user.get("id"):
        raise PermissionError("Utilisateur Telegram absent")
    return user, auth, pairs.get("query_id")


def webapp_allowed(acc, key):
    if not acc or not acc.get("can_live"):
        return False
    allowed = acc.get("allowed_measures")
    return not allowed or key in allowed


def webapp_snapshot(acc):
    mac = acc["mac"].upper()
    with state_lock:
        r = rings.get(mac)
        live = json.loads(json.dumps(r, default=str)) if r else None
        g = (gateways.get(r["gateway"]) if r else None) or {}
    if live and live["online"] and live["statusTs"] and now() - live["statusTs"] > OFFLINE_AFTER:
        live["online"] = False
    try:
        latest = dbq.latest_values(acc["ring_id"])
    except Exception:
        latest = {}
    visible = [k for k in WEBAPP_MEASURES if not acc.get("allowed_measures") or k in acc["allowed_measures"]]
    ring = None
    if live:
        ring = {k: live.get(k) for k in ("online", "ring", "worn", "battery", "charging", "deviceName", "gateway",
                                          "model", "firmware", "statusTs", "unbound", "unboundTs", "boundTs", "removedTs", "wornTs", "outTs", "pending", "errors")}
        ring["values"] = {k: v for k, v in (live.get("values") or {}).items() if k in visible}
        ring["gatewayOnline"] = bool(g.get("online", live["online"]))
    return {
        "now": now(),
        "ring": ring,
        "latest": {k: v for k, v in latest.items() if k in visible},
        "info": {"name": acc["ring_name"], "mac": acc["mac"].upper(), "model": acc.get("model"),
                 "user": acc.get("firstname") or ""},
        "rights": {"history": bool(acc.get("can_view_history")),
                   "measures": [k for k in visible if webapp_allowed(acc, k)], "visible": visible},
        "limits": WEBAPP_LIMITS,
        "wear": {"check": WEAR_CHECK_SECONDS, "reuse": WEAR_REUSE_SECONDS},
    }


def webapp_acc_from_request():
    body = request.get_json(silent=True) or {}
    token = body.get("token") or request.args.get("token")
    try:
        acc = dbq.webapp_session_access(token)
    except Exception as e:
        return None, fail(f"Base indisponible : {e}", 503)
    if not acc:
        return None, fail("Accès retiré ou session expirée", 403)
    return acc, None


@app.route("/webapp/ring/<ring_key>")
def webapp_page(ring_key):
    mac = mac_from_key(ring_key)
    if not mac:
        return "Bague inconnue", 404
    return render_template("webapp.html", ring_key=mac.replace(":", "").lower())


@app.post("/api/webapp/open")
def webapp_open():
    body = request.get_json(silent=True) or {}
    mac = mac_from_key(body.get("ring"))
    if not mac:
        return fail("Bague inconnue", 404)
    try:
        user, auth, qid = validate_init_data(body.get("initData"))
    except (PermissionError, ValueError, json.JSONDecodeError) as e:
        return fail(e, 401)
    except RuntimeError as e:
        return fail(e, 503)
    try:
        acc = dbq.webapp_access(user["id"], mac)
        if not acc:
            return fail("Cette bague ne t'est pas affectée / This ring is not assigned to you", 403)
        token = dbq.webapp_open_session(acc["telegram_user_id"], acc["ring_id"], auth, qid)
    except Exception as e:
        log.exception("webapp open")
        return fail(f"Base indisponible : {e}", 503)
    add_event("info", f"Web App ouverte par {user.get('first_name') or user['id']} ({acc['ring_name']})", mac)
    return ok(token=token, **webapp_snapshot(acc))


@app.post("/api/webapp/data")
def webapp_data():
    acc, err = webapp_acc_from_request()
    if err:
        return err
    return ok(**webapp_snapshot(acc))


@app.post("/api/webapp/cmd")
def webapp_cmd():
    acc, err = webapp_acc_from_request()
    if err:
        return err
    cmd = (request.get_json(silent=True) or {}).get("cmd")
    if cmd not in WEBAPP_MEASURES or not webapp_allowed(acc, cmd):
        return fail("Mesure non autorisée / Measurement not allowed", 403)
    mac = acc["mac"].upper()
    with state_lock:
        r = rings.get(mac)
        state = dict(r) if r else None
    if not state or not state["statusTs"]:
        return fail("Aucune TV ne signale cette bague", 409, reason="unknown")
    if not state["online"] or now() - state["statusTs"] > OFFLINE_AFTER:
        return fail("TV hors ligne / TV offline", 409, reason="gateway_offline")
    if state["ring"] != "connected":
        return fail("Hors portée / Out of range", 409, reason="ring_disconnected")
    res, code = send_ring_cmd(mac, cmd, {}, "webapp", f"Web App · {acc.get('firstname') or acc['id_telegram']}")
    return jsonify(res), code


@app.post("/api/webapp/check")
def webapp_check():
    """Bouton « État / Status » : une mesure HR sert de test de port (droit « voir » suffit).
    Si une mesure tourne déjà, on la suit au lieu d'en lancer une autre."""
    acc, err = webapp_acc_from_request()
    if err:
        return err
    mac = acc["mac"].upper()
    with state_lock:
        r = rings.get(mac)
        state = json.loads(json.dumps(r, default=str)) if r else None
    if not state or not state["statusTs"]:
        return fail("Aucune TV ne signale cette bague", 409, reason="unknown")
    if not state["online"] or now() - state["statusTs"] > OFFLINE_AFTER:
        return fail("TV hors ligne / TV offline", 409, reason="gateway_offline")
    if state["ring"] != "connected":
        return fail("Hors portée / Out of range", 409, reason="ring_disconnected")
    running = [k for k in state["pending"] if k in MEASURES]
    if running:
        k = running[0]
        return ok(cmd=k, reqId=state["pending"][k].get("reqId"), already=True)
    res, code = send_ring_cmd(mac, "hr", {}, "webapp", f"Web App État · {acc.get('firstname') or acc['id_telegram']}")
    if code == 409 and res.get("busy"):
        with state_lock:
            p = (rings.get(mac) or {}).get("pending", {}).get(res["busy"]) or {}
        return ok(cmd=res["busy"], reqId=p.get("reqId"), already=True)
    if not res.get("ok"):
        return jsonify(res), code
    return ok(cmd="hr", reqId=res.get("reqId"), already=bool(res.get("already")))


@app.post("/api/webapp/history")
def webapp_history():
    acc, err = webapp_acc_from_request()
    if err:
        return err
    if not acc.get("can_view_history"):
        return fail("Historique non autorisé", 403)
    body = request.get_json(silent=True) or {}
    key = body.get("type", "hr")
    visible = [k for k in WEBAPP_MEASURES if not acc.get("allowed_measures") or k in acc["allowed_measures"]]
    if key not in visible:
        return fail("Mesure non autorisée", 403)
    hours = min(max(int(body.get("hours", 24)), 1), 24 * 90)
    try:
        rows = dbq.history(acc["mac"], DB_METRIC[key], 500)
    except Exception as e:
        return fail(f"Base indisponible : {e}", 503)
    limit = now() - hours * 3600
    out = [{"ts": int(x["time"].timestamp()), "value": x["value"], "status": x["status"], "reason": x["reason"],
            "dur": (x["extra"] or {}).get("duration_s")}
           for x in rows if x["time"].timestamp() >= limit]
    return ok(rows=out)


@app.post("/api/webapp/close")
def webapp_close():
    body = request.get_json(silent=True) or {}
    if not body:
        try:
            body = json.loads(request.data or b"{}")
        except Exception:
            body = {}
    try:
        dbq.webapp_close_session(body.get("token"))
    except Exception:
        pass
    return ok()


# ---------------------------------------------------------------------------- temps réel

@app.route("/stream")
@login_required
def stream():
    q = queue.Queue(maxsize=500)
    subscribers.append(q)

    def gen():
        try:
            yield "retry: 3000\n\n"
            while True:
                try:
                    yield f"data: {q.get(timeout=20)}\n\n"
                except queue.Empty:
                    yield ": ping\n\n"
        finally:
            if q in subscribers:
                subscribers.remove(q)

    return Response(gen(), mimetype="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def main():
    if ADMIN_PASSWORD == "admin":
        log.warning("QRING_ADMIN_PASSWORD absent du .env : mot de passe par défaut « admin » — à changer !")
    dbq.test()
    seed_from_db()
    load_zones()
    dbq.start_worker()
    start_mqtt()
    threading.Thread(target=watchdog, daemon=True).start()
    log.info("QRing Admin sur http://0.0.0.0:%d (broker %s:%d, préfixe %s, PostgreSQL %s)",
             PORT, MQTT_HOST, MQTT_PORT, PREFIX, dbq.status()["message"])
    app.run(host="0.0.0.0", port=PORT, threaded=True, debug=False)


if __name__ == "__main__":
    main()
