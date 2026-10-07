"""
QRingClient API — service de l'app téléphone QRingClient (Flutter).

Indépendant de QRing Admin (Flask) : ce service a son propre process pm2.
- Se connecte lui-même à Mosquitto : état des bagues en temps réel (flux SSE vers l'app)
- Lit PostgreSQL : comptes, droits, historique (QRing Admin reste celui qui ENREGISTRE les mesures)
- Envoie les mesures demandées par l'app sur eis/colmi/<MAC>/cmd (reqId « app-… »),
  même règle que l'admin et le bot : une seule mesure à la fois par bague
- Alertes (retirée, hors portée, Gateway RHM hors ligne, batterie faible) : liste dans l'app,
  flux en direct et notifications Firebase (FCM) même app fermée

Lancement :  pm2 start client_api.py --name qring-client-api --interpreter ./venv/bin/python
Configuration : le même .env que QRing Admin et le bot (voir .env.example, section QRingClient).
"""
import json
import logging
import os
import queue
import re
import threading
import time
import uuid
from functools import wraps
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

# ---------------------------------------------------------------------------- .env (avant dbq)
HERE = Path(__file__).resolve().parent
ENV_PATH = None
for candidate in [os.getenv("QRING_ENV_FILE"), HERE / ".env", HERE.parent / ".env"]:
    if candidate and Path(candidate).is_file():
        load_dotenv(candidate, override=False)
        ENV_PATH = ENV_PATH or Path(candidate)

# Durées estimées des mesures (barre de progression de l'app) : UNIQUEMENT le .env de client_api,
# MEASURE_ESTIMATE_<MESURE>_SECONDS. Relu automatiquement quand le .env change (pas besoin de redémarrer).
_EST_BUILTIN = {"all": 120, "hr": 40, "spo2": 40, "temp": 40, "hrv": 35, "stress": 30,
                "fatigue": 30, "health": 30, "steps": 15, "battery": 10, "bp": 40, "sleep": 30}
_est = {"mtime": None, "values": {}}


def measure_seconds():
    try:
        mt = ENV_PATH.stat().st_mtime if ENV_PATH else None
    except OSError:
        mt = None
    if _est["mtime"] != mt or not _est["values"]:
        env = dotenv_values(ENV_PATH) if ENV_PATH and mt else {}
        out = {}
        for k, d in _EST_BUILTIN.items():
            name = f"MEASURE_ESTIMATE_{k.upper()}_SECONDS"
            raw = env.get(name) if ENV_PATH else os.getenv(name)
            try:
                out[k] = max(5, min(600, int(str(raw).strip()))) if raw not in (None, "") else d
            except ValueError:
                out[k] = d
        _est.update(mtime=mt, values=out)
    return _est["values"]


def _env_number(name, default, cast, pattern):
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        raw = default
    m = re.search(pattern, str(raw))
    if not m:
        m = re.search(pattern, str(default))
    return cast(m.group(0).replace(",", "."))


def env_int(name, default):
    return _env_number(name, default, int, r"-?\d+")


def env_float(name, default):
    return _env_number(name, default, float, r"-?\d+(?:[.,]\d+)?")


import paho.mqtt.client as mqtt
import race  # noqa: E402
from flask import Flask, Response, g, jsonify, request, send_file  # noqa: E402
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer  # noqa: E402

import clientdb  # noqa: E402
import photos  # noqa: E402
import dbq  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("qring.client")

MQTT_HOST = os.getenv("MQTT_HOST", "51.83.40.138")
MQTT_PORT = env_int("MQTT_PORT", "1883")
MQTT_USER = os.getenv("MQTT_USER", "")
MQTT_PASS = os.getenv("MQTT_PASSWORD", os.getenv("MQTT_PASS", ""))
PREFIX = (os.getenv("MQTT_PREFIX") or os.getenv("MQTT_TOPIC", "eis/colmi/#")).replace("#", "").strip("/")
OFFLINE_AFTER = env_int("QRING_OFFLINE_AFTER", "150")

PORT = env_int("CLIENT_API_PORT", "5060")
TOKEN_DAYS = max(1, env_int("CLIENT_TOKEN_DAYS", "30"))
ALERT_CONFIRM = max(0, env_int("CLIENT_ALERT_CONFIRM_SECONDS", os.getenv("TELEGRAM_ALERT_CONFIRM_SECONDS") or "60"))
BATTERY_LOW = env_int("CLIENT_ALERT_BATTERY_LOW", os.getenv("TELEGRAM_ALERT_BATTERY_LOW") or "20")
WEAR_CHECK_SECONDS = max(5, env_int("TELEGRAM_WEAR_CHECK_SECONDS", "15"))
FCM_FILE = os.getenv("FCM_SERVICE_ACCOUNT_FILE", "").strip()
# HTTPS direct (sinon mettre le service derrière Nginx en HTTPS) : chemins du certificat et de la clé
SSL_CERT = os.getenv("CLIENT_API_SSL_CERT", "").strip()
SSL_KEY = os.getenv("CLIENT_API_SSL_KEY", "").strip()

SECRET = (os.getenv("CLIENT_API_SECRET") or os.getenv("QRING_SECRET_KEY") or "").strip()
if not SECRET:
    SECRET = uuid.uuid4().hex + uuid.uuid4().hex
    log.warning("CLIENT_API_SECRET absent du .env : clé temporaire, les téléphones devront se reconnecter "
                "à chaque redémarrage du service.")
signer = URLSafeTimedSerializer(SECRET, salt="qringclient-v1")

MEASURES = ["hr", "spo2", "temp", "bp", "hrv", "stress", "fatigue", "health", "all"]
# Mesures proposées par défaut (allowed_measures NULL) : la tension n'existe pas sur toutes les bagues
DEFAULT_MEASURES = ["hr", "spo2", "temp", "hrv", "stress", "fatigue", "health", "steps"]
LIMITS = {"hr": 60, "spo2": 90, "temp": 60, "bp": 60, "hrv": 60, "stress": 60, "fatigue": 60, "health": 60,
          "steps": 30, "all": 200}
DB_METRIC = {"hr": "heart_rate", "spo2": "spo2", "temp": "temperature", "bp": "blood_pressure",
             "hrv": "hrv", "stress": "stress", "fatigue": "fatigue", "health": "health_check",
             "steps": "steps", "battery": "battery"}
APP_TYPE = {v: k for k, v in DB_METRIC.items()}

app = Flask(__name__)


def now():
    return int(time.time())


def tv_ts(v):
    """Heure envoyée par la Gateway RHM (secondes ou millisecondes) → secondes, 0 si absente."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 1e9:
        return 0
    return min(int(v / 1000 if v > 1e12 else v), now())



# ============================================================================ état des bagues (MQTT)

lock = threading.RLock()
rings = {}        # mac -> état en direct
gateways = {}     # nom -> {"online", "statusTs"}
client_settings = {"showGatewayType": True}   # réglages globaux publiés par l'admin (eis/colmi/config/client)
ring_ids = {}     # mac -> rings.id en base
stats = {"messages": 0, "lastMessage": 0, "statusSeen": {}}   # diagnostic (/api/client/health)


def new_ring(mac):
    return {"mac": mac, "name": "", "model": "", "firmware": "", "gateway": "", "deviceName": "",
            "online": False, "ring": "unknown", "worn": None, "battery": None, "charging": False,
            "gatewayType": "android", "statusTs": 0, "unboundTs": 0, "boundTs": 0, "removedTs": 0, "batteryTs": 0, "wornTs": 0, "outTs": 0, "pending": {}, "errors": {}, "values": {}}


def mac_from_topic(t):
    t = t.upper()
    return ":".join(t[i:i + 2] for i in range(0, 12, 2)) if len(t) == 12 else t


def topic_mac(mac):
    return mac.replace(":", "").replace("-", "").upper()


# Mesures envoyées sur le topic de la gateway choisie (eis/colmi/gateway/<nom>/cmd) : seule cette Pi
# les reçoit et les fait avec colmi_r02_client. Les autres restent sur eis/colmi/<MAC>/cmd.
GW_TOPIC_CMDS = {c.strip() for c in os.getenv("GW_TOPIC_CMDS", "hrv,stress,fatigue,health,steps").split(",") if c.strip()}


def publish_to_gateway(mac, gw, msg):
    """Publie une commande pour la gateway gw : topic gateway pour GW_TOPIC_CMDS, sinon topic de la bague."""
    if msg.get("cmd") in GW_TOPIC_CMDS and gw:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", gw)
        return mqttc.publish(f"{PREFIX}/gateway/{safe}/cmd", json.dumps(dict(msg, mac=mac)), qos=1)
    return mqttc.publish(f"{PREFIX}/{topic_mac(mac)}/cmd", json.dumps(msg), qos=1)


def mac_from_key(key):
    k = re.sub(r"[^0-9a-fA-F]", "", str(key or "")).upper()
    return ":".join(k[i:i + 2] for i in range(0, 12, 2)) if len(k) == 12 else None


def seed_from_db():
    try:
        rows = dbq.load_rings()
    except Exception as e:
        log.warning("Bagues PostgreSQL non chargées : %s", e)
        return
    with lock:
        for row in rows:
            mac = row["mac"].upper()
            ring_ids[mac] = row["id"]
            r = rings.setdefault(mac, new_ring(mac))
            r.update({"name": row["name"] or "", "model": row["model"] or "", "firmware": row["fw_version"] or "",
                      "gateway": row["gateway"] or "", "charging": bool(row["charging"]),
                      "battery": int(row["battery"]) if row["battery"] is not None else None,
                      "worn": True if row["wear_status"] == "worn" else False if row["wear_status"] == "removed" else None,
                      "statusTs": 0})
            for m in row["latest"]:
                typ = APP_TYPE.get(m["metric"])
                if not typ:
                    continue
                ex = m["extra"] or {}
                data = {"value": m["value"]}
                if typ == "bp":
                    data = {"sbp": ex.get("sbp", m["value"]), "dbp": ex.get("dbp")}
                if typ == "steps":
                    data = {"steps": int(m["value"] or 0)}
                r["values"][typ] = {"ts": int(m["time"].timestamp()), "data": data,
                                    "dur": ex.get("duration_s"), "source": ex.get("origin") or "db"}
    log.info("%d bague(s) chargée(s) depuis PostgreSQL", len(rows))


def ring_id(mac):
    rid = ring_ids.get(mac)
    if rid is None:
        try:
            rid = clientdb.ring_id_by_mac(mac)
        except Exception:
            rid = None
        if rid is not None:
            ring_ids[mac] = rid
    return rid


def on_connect(client, userdata, flags, reason_code, properties=None):
    if reason_code == 0 or str(reason_code) == "Success":
        client.subscribe(f"{PREFIX}/#", qos=1)
        log.info("Connecté au broker %s:%d", MQTT_HOST, MQTT_PORT)
    else:
        log.error("Connexion broker refusée : %s", reason_code)


def on_message(client, userdata, msg):
    try:
        p = json.loads(msg.payload.decode("utf-8"))
    except Exception:
        return
    if not isinstance(p, dict):
        return
    stats["messages"] += 1
    stats["lastMessage"] = now()
    parts = msg.topic.split("/")
    base = PREFIX.split("/")
    if parts[: len(base)] != base:
        return
    rest = parts[len(base):]
    if rest == ["config", "photos"]:
        # Photos des résidents (versions) publiées par l'admin : l'app recharge celles qui ont changé
        new = {str(k).upper(): v for k, v in (p.get("photos") or {}).items()}
        changed = [m for m in set(new) | set(photos_cfg) if new.get(m) != photos_cfg.get(m)]
        photos_cfg.clear()
        photos_cfg.update(new)
        for m in changed:
            push_ring(m)
        return
    if rest == ["config", "zones"]:
        # Noms des pièces (zones) publiés par l'admin : « Chambre 12 », « Salon »…
        zones_cfg["names"] = {str(k): str(v) for k, v in (p.get("names") or {}).items() if v}
        zones_cfg["rings"] = {str(k).upper(): v for k, v in (p.get("rings") or {}).items() if isinstance(v, dict)}
        return
    if rest == ["config", "client"]:
        client_settings["showGatewayType"] = bool(p.get("showGatewayType", True))
        # Bagues sur TV Android : boutons « Mesurer HR + SpO2 » / « Autres mesures » (global + par bague)
        client_settings["tvShowAll"] = p.get("tvShowAll", True) is not False
        client_settings["tvShowOther"] = p.get("tvShowOther", True) is not False
        client_settings["tvButtons"] = {str(k).upper(): v for k, v in (p.get("tvButtons") or {}).items()
                                        if isinstance(v, dict)}
        for m in list(rings):
            push_ring(m)
        # Durées estimées : ignorées ici, elles viennent du .env de client_api
        log.info("Réglages Client RHM : %s · durées estimées (.env) : %s", client_settings, measure_seconds())
        return
    try:
        if len(rest) >= 3 and rest[0] == "gateway" and rest[2] != "presence":
            if rest[2] == "status":
                with lock:
                    g = {"online": bool(p.get("online")), "statusTs": now(), "ringMac": p.get("ringMac") or "",
                         "name": p.get("gateway") or rest[1],
                         "type": str(p.get("gatewayType") or "android").lower(),
                         # Gateway multi-bagues (zones) : bagues suivies, écoute passive, mesure en cours
                         "multi": bool(p.get("multi")), "scanner": bool(p.get("scanner")), "busy": p.get("busy"),
                         "rings": {str(x.get("mac") or "").upper(): x.get("role") for x in (p.get("rings") or [])
                                   if isinstance(x, dict) and x.get("mac")}}
                    # Clé = nom du topic ET nom affiché (« GW Test1-RHM ») : la bague ne connaît que ce dernier
                    keys = {rest[1], p.get("gateway") or "", p.get("deviceName") or ""} - {""}
                    for k in keys:
                        gateways[k] = g
                    # Gateway en veille (course perdue ou priorité Android) : elle n'a plus la bague
                    rm = (p.get("ringMac") or "").upper()
                    if p.get("ring") == "standby" and rm in rings:
                        rings[rm].setdefault("gwSeen", {})[p.get("gateway") or rest[1]] = {
                            "ts": now(), "online": True, "ring": "standby"}
                    # Bagues dissociées de cette Gateway RHM : leur état dépend de ce statut
                    unbound = [m for m, r in rings.items() if r["ring"] == "unbound" and r["gateway"] in keys]
                for m in unbound:
                    push_ring(m)
        elif len(rest) == 3 and rest[0] == "gateway" and rest[2] == "presence":
            on_presence(p.get("gateway") or rest[1], p)
        elif len(rest) == 2 and len(rest[0]) == 12 and rest[1] == "location":
            # Localisation (retenue) : où se trouve la bague, d'après le dernier test de portée
            with lock:
                rings.setdefault(mac_from_topic(rest[0]), new_ring(mac_from_topic(rest[0])))["location"] = p
        elif len(rest) == 2 and len(rest[0]) == 12 and rest[1] not in ("profile", "race"):
            handle_ring(mac_from_topic(rest[0]), rest[1], p)
    except Exception:
        log.exception("message %s", msg.topic)


def other_gateway_holds(mac, p):
    """Plusieurs Gateway RHM pour la même bague : on garde celle qui l'a « connectée »."""
    gw = p.get("gateway")
    if not gw:
        return False
    t = now()
    with lock:
        seen = rings.setdefault(mac, new_ring(mac)).setdefault("gwSeen", {})
        seen[gw] = {"ts": t, "online": bool(p.get("online")), "ring": p.get("ring")}
        return p.get("ring") != "connected" and any(
            n != gw and v["online"] and v["ring"] == "connected" and t - v["ts"] < 120 for n, v in seen.items())


def handle_ring(mac, sub, p):
    if sub == "status" and other_gateway_holds(mac, p):
        return
    with lock:
        r = rings.setdefault(mac, new_ring(mac))
        was_worn = r["worn"]
        if sub == "cmd":
            # Commande d'un autre lanceur (admin, bot, Web App) : la bague devient occupée
            cmd = p.get("cmd")
            if cmd in MEASURES and cmd not in r["pending"]:
                r["pending"][cmd] = {"since": now(), "requested": now(), "reqId": p.get("reqId"), "confirmed": False}
                r["errors"].pop(cmd, None)
            else:
                return
        else:
            if sub != "reach":   # les tests de portée viennent de toutes les gateways : pas la « via »
                r["gateway"] = p.get("gateway") or r["gateway"]
            if sub == "status" and "online" in p and p.get("online") is not False:
                # Type de gateway : « linux » si le .env de la gateway le dit, sinon TV « android »
                r["gatewayType"] = str(p.get("gatewayType") or "android").lower()
            if p.get("ringModel"):
                r["model"] = p["ringModel"]
            if sub == "status":
                if mac not in stats["statusSeen"]:
                    log.info("Premier statut reçu : bague %s via Gateway RHM « %s » (online=%s, ring=%s)",
                             mac, p.get("gateway"), p.get("online"), p.get("ring"))
                stats["statusSeen"][mac] = now()
                # Heures envoyées par la Gateway RHM (unboundAt / boundAt / removedAt, gardées même après
                # redémarrage) ; anciennes versions : « ts » du statut ou heure vue par ce service.
                ts = tv_ts(p.get("ts")) or now()
                if p.get("ring") == "unbound":
                    if tv_ts(p.get("unboundAt")):
                        r["unboundTs"] = tv_ts(p.get("unboundAt"))
                    elif r["ring"] != "unbound" or not r.get("unboundTs"):
                        r["unboundTs"] = ts
                else:
                    if r["ring"] == "unbound" and p.get("ring") not in (None, "no_ring", "unknown"):
                        r["unboundTs"], r["boundTs"] = 0, ts
                    if tv_ts(p.get("boundAt")):
                        r["boundTs"] = tv_ts(p.get("boundAt"))
                if "removedAt" in p:
                    r["removedTsTv"] = tv_ts(p.get("removedAt"))
                if not p.get("online") and p.get("ring") in (None, "unknown") and r["statusTs"]:
                    # Gateway RHM coupée (message de dernière volonté) : on garde le dernier état connu
                    # de la bague (portée / retirée / hors portée) et l'heure du dernier vrai statut
                    r["online"] = False
                else:
                    # Batterie : la dernière valeur connue reste affichée (bague dissociée → « il y a … »)
                    batt = p.get("battery")
                    if batt is not None and (batt != r["battery"] or not r.get("batteryTs")):
                        r["batteryTs"] = now()
                    # Vrai nom Bluetooth de la bague (ex. « R10_6401 »), envoyé par la GATEWAY RHM
                    if p.get("ringName") and p.get("ring") != "unbound":
                        r["bleName"] = p["ringName"]
                    r.update({"online": bool(p.get("online")), "ring": p.get("ring", r["ring"]),
                              "name": r["name"] or p.get("ringName") or "", "firmware": p.get("firmware") or r["firmware"],
                              "battery": batt if batt is not None else r["battery"],
                              "charging": bool(p.get("charging")) if batt is not None else r["charging"],
                              "worn": p.get("worn", r["worn"]), "deviceName": p.get("deviceName") or r["deviceName"],
                              # TV Android : force du signal de la bague connectée (dBm)
                              "rssi": p.get("rssi") if p.get("ring") == "connected" else None,
                              "statusTs": now()})
            else:
                handle_result(r, sub, p)
        # Heure du retrait : celle de la Gateway RHM si elle l'envoie, sinon vue par ce service ;
        # effacée dès que la bague est de nouveau portée
        if r["worn"] is False:
            if r.get("removedTsTv"):
                r["removedTs"] = r["removedTsTv"]
            elif was_worn is not False:
                r["removedTs"] = now()
        else:
            r["removedTs"] = r["removedTsTv"] = 0
        # Heure de l'état : portée (dernière preuve) / hors portée (depuis)
        if r["worn"] is True and was_worn is not True:
            r["wornTs"] = now()
        if r["ring"] in ("disconnected", "connecting"):
            r["outTs"] = r.get("outTs") or now()
        elif r["ring"] == "connected":
            r["outTs"] = 0
        snapshot = json.loads(json.dumps(r, default=str))
        free = not any(k in MEASURES for k in r["pending"])
    alerts.observe(mac, snapshot)
    push_ring(mac)
    if free and waiters.get(mac):
        notify_free(mac)


def handle_result(r, sub, p):
    st = p.get("status")
    req = p.get("reqId")
    if st in ("ok", "measuring") and sub != "reach" and p.get("gateway"):
        seen_by_measure(r["mac"], p["gateway"])
    if sub == "reach" and st == "ok" and p.get("gateway") and p.get("rssi") is not None:
        e = (presence.get(r["mac"].upper()) or {}).get(p["gateway"])
        if e is not None:
            e.update(rssi=p["rssi"], ts=now(), misses=0)     # test de portée réussi = entendue à l'instant
    if st == "error" and p.get("error") == "ring_disconnected" and sub != "reach":
        # Mesure qui n'a pas joint la bague : c'est test_reachable qui dit si elle est hors portée
        if scan_mode(r["mac"]):
            threading.Thread(target=confirm_reach, args=(r["mac"], f"mesure {sub} sans réponse"), daemon=True).start()
        elif linux_gateways(r["mac"]):
            # 3 essais ratés sur la Pi de la mesure : « Mesure échouée » ; c'est le test de portée (tout de
            # suite, sur toutes les Pi de ses zones) qui dit « hors portée » ou « détectée »
            p = dict(p, error="measure_failed", reason="ring_disconnected")
            threading.Thread(target=lambda m=r["mac"]: (time.sleep(3), locate(m)), daemon=True).start()
    # Test de portée demandé à une gateway pendant une localisation : réponse pour le fil qui attend
    if sub == "reach" and req in reach_waiters:
        if st in ("ok", "error"):
            reach_waiters[req].put(p)
        return
    # Mesure adressée à une gateway qui n'a pas joint la bague : on passe à la suivante du classement
    route = routes.get(req)
    if route and st == "error" and p.get("error") in ("ring_disconnected", "timeout") \
            and route["i"] + 1 < len(route["order"]):
        route["i"] += 1
        nxt = route["order"][route["i"]]
        log.info("Mesure %s (%s) : « %s » n'a pas joint la bague → essai sur « %s »", sub, req, p.get("gateway"), nxt)
        publish_to_gateway(r["mac"], nxt, {"cmd": route["cmd"], "reqId": req, "gateway": nxt,
                                           "oneTry": route["i"] + 1 < len(route["order"])})
        return
    if route and st in ("ok", "error"):
        routes.pop(req, None)
    # Roaming « course » (Gateway Linux) : on attend les autres gateways avant d'afficher une erreur
    if race.is_duplicate_ok(r, sub, p) or race.hold_error(r, sub, p, race.candidates(gateways, r["mac"])):
        return
    if st in ("ok", "error"):
        race.settle(r, p)
    if st in ("measuring", "searching"):
        old = r["pending"].get(sub) or {}
        r["pending"][sub] = {"since": now(), "requested": old.get("requested") or now(),
                             "reqId": p.get("reqId") or old.get("reqId"), "confirmed": True}
        r["errors"].pop(sub, None)
        return
    pnd = r["pending"].pop(sub, None) or {}
    ts = p.get("ts") or now()
    if (gateways.get(p.get("gateway") or "") or {}).get("type") == "linux":
        # Gateway Linux : résultat daté à la réception (heure du serveur). Une Pi dont l'horloge retarde
        # ne bloque plus l'écran de mesure de l'app (« Connexion à la bague… » sans fin)
        ts = now()
    started = pnd.get("since") or pnd.get("requested")
    dur = max(0, now() - started) if started else None
    if st == "ok":
        data = {k: v for k, v in p.items() if k not in (
            "reqId", "type", "status", "source", "ringMac", "ringModel", "gateway", "ts")}
        if sub == "sleep":
            data = {k: v for k, v in data.items() if k not in ("nights", "phases")}
        by = phone_by(p.get("reqId") or pnd.get("reqId"))
        req = p.get("reqId") or pnd.get("reqId")
        meta = {"ts": ts, "dur": dur, "source": "phone" if by else p.get("source"), "by": by, "via": phone_via(req),
                "reqId": req}
        r["values"][sub] = dict(meta, data=data)
        r["errors"].pop(sub, None)
        if sub == "all":
            for k in ("hr", "spo2", "temp", "hrv", "stress", "fatigue", "health"):
                if k in data:
                    r["values"][k] = dict(meta, data={"value": data[k]})
            if "sbp" in data:
                r["values"]["bp"] = dict(meta, data={"sbp": data["sbp"], "dbp": data.get("dbp")})
        if sub == "battery":
            r["battery"] = data.get("value", r["battery"])
            r["charging"] = bool(data.get("charging"))
            r["batteryTs"] = ts
        if sub in MEASURES:
            r["worn"] = True
            r["wornTs"] = max(r.get("wornTs") or 0, tv_ts(ts) or now())
    elif st == "error":
        err = p.get("error", "error")
        r["errors"][sub] = {"ts": ts, "code": err, "dur": dur}
        if err == "ring_removed":
            r["worn"] = False
        elif err in ("measure_failed", "timeout") and sub in MEASURES:
            alerts.q.put((r["mac"], "measure_failed", {"what": "HR + SpO2" if sub == "all" else sub.upper()}))


mqttc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"qring-client-api-{uuid.uuid4().hex[:8]}")


def start_mqtt():
    mqttc.on_connect = on_connect
    mqttc.on_message = on_message
    if MQTT_USER:
        mqttc.username_pw_set(MQTT_USER, MQTT_PASS)
    mqttc.reconnect_delay_set(min_delay=1, max_delay=30)
    mqttc.connect_async(MQTT_HOST, MQTT_PORT, keepalive=30)
    mqttc.loop_start()


def linux_online(mac):
    """Bague sur Gateway Linux : en ligne si au moins une Pi de ses zones envoie son statut
    (gateway_multi.py, toutes les ~60 s) — pas de minuteur sur le statut de la bague elle-même."""
    t = now()
    with lock:
        for g in gateways.values():
            if g.get("type") == "linux" and g.get("online") and t - (g.get("statusTs") or 0) <= OFFLINE_AFTER and (
                    (g.get("ringMac") or "").upper() == mac.upper() or mac.upper() in (g.get("rings") or {})):
                return True
    return False


def gateway_online(r):
    """Gateway en ligne : statut récent (moins de QRING_OFFLINE_AFTER secondes).
    Bague dissociée : la TV ne publie plus sur le topic de la bague ({"online": false, "ring": "unbound"}),
    on regarde alors le statut du gateway lui-même (topic gateway/<nom>/status)."""
    if r.get("ring") == "unbound":
        with lock:
            g = gateways.get(r.get("gateway") or "")
        return bool(g and g["online"] and now() - g["statusTs"] <= OFFLINE_AFTER)
    if r.get("gatewayType") == "linux" and r.get("mac"):
        return linux_online(r["mac"])
    return bool(r["online"] and r["statusTs"] and now() - r["statusTs"] <= OFFLINE_AFTER)


zones_cfg = {"names": {}, "rings": {}}
photos_cfg = {}      # MAC → version de la photo du résident


def zone_name(gw):
    return zones_cfg["names"].get(gw) or gw if gw else None


def zone_info(mac, r):
    """Pièce actuelle / dernière pièce / zone principale de la bague (pour le Client RHM V2)."""
    loc = r.get("location") or {}
    z = zones_cfg["rings"].get(mac.upper()) or {}
    cur = loc.get("gateway") if loc.get("reachable") else None
    if cur and loc.get("mode") == "scan" and now() - (loc.get("seenTs") or 0) > 120:
        cur = None     # entendue il y a plus de 2 min : plus « dans » cette pièce
    last = cur or r.get("lastZoneGw") or loc.get("gateway")
    return {"zone": zone_name(cur), "lastZone": zone_name(last), "zoneGateway": cur,
            # Dernière détection (Pi + heure) : pièce et heure où le test de portée l'a entendue la dernière fois
            "lastSeenTs": loc.get("seenTs"), "lastSeenZone": zone_name(loc.get("seenGateway") or last),
            "mainZone": zone_name(z.get("main")), "secondaryZones": [zone_name(g2) for g2 in z.get("secondary") or []],
            "zoneRole": "main" if cur and cur == z.get("main") else "secondary" if cur and cur in (z.get("secondary") or []) else None}


def tv_button(mac, k):
    ex = (client_settings.get("tvButtons") or {}).get(mac.upper()) or {}
    if ex.get(k) is not None:
        return bool(ex[k])
    return client_settings.get("tvShowAll" if k == "all" else "tvShowOther", True) is not False


def live_state(mac, acc=None):
    """État en direct pour l'app, filtré selon les droits du compte."""
    with lock:
        r = rings.get(mac)
        r = json.loads(json.dumps(r, default=str)) if r else new_ring(mac)
    visible = set(visible_measures(acc)) | {"battery", "sleep"} if acc else None
    vals = r["values"]
    if visible is not None:
        # Valeur d'un « Actualiser » (HR) toujours montrée : c'est le test de port
        vals = {k: v for k, v in vals.items() if k in visible or v.get("via") == "r"}
    return {"online": gateway_online(r), "ring": r["ring"], "worn": r["worn"], "battery": r["battery"],
            "charging": r["charging"], "gateway": r["gateway"], "deviceName": r["deviceName"],
            "gatewayType": r.get("gatewayType") or "android", "showGatewayType": client_settings["showGatewayType"],
            # Durées estimées des mesures : .env de client_api (MEASURE_ESTIMATE_*_SECONDS)
            "measureSeconds": measure_seconds(),
            "rssi": r.get("rssi"),
            # Boutons du Client RHM pour une bague sur TV Android (réglage admin : global, puis exception par bague)
            "tvShowAll": tv_button(mac, "all"), "tvShowOther": tv_button(mac, "other"),
            # Localisation seulement pour une bague sur Gateway Linux (pas pour une bague tenue par une TV)
            "location": {k: (r.get("location") or {}).get(k)
                         for k in ("gateway", "reachable", "rssi", "ranking", "ts", "seenTs", "seenGateway",
                                   "prevGateway", "prevTs", "mode")}
            if r.get("location") and (r.get("gatewayType") or "android") == "linux" else None,
            "model": r["model"], "firmware": r["firmware"], "statusTs": r["statusTs"],
            "unboundTs": r.get("unboundTs") or 0, "boundTs": r.get("boundTs") or 0, "removedTs": r.get("removedTs") or 0,
            "bleName": r.get("bleName") or "",
            "batteryTs": r.get("batteryTs") or 0, "outTs": r.get("outTs") or 0,
            "wornTs": r.get("wornTs") or max([int(v.get("ts") or 0) for k, v in r["values"].items()
                                               if k in MEASURES] or [0]),
            # Mesure réellement en cours d'abord (confirmée par la gateway) : avec le script Linux, la SpO2
            # demandée attend que la HR soit finie → l'app affiche « HR en cours » puis « SpO2 en cours »
            "pending": {k: {"since": v.get("since"), "requested": v.get("requested"), "confirmed": v.get("confirmed"),
                            "waitFor": v.get("waitFor")}
                        for k, v in sorted(r["pending"].items(),
                                           key=lambda kv: (not kv[1].get("confirmed"), kv[1].get("since") or 0))},
            "errors": r["errors"], "values": vals, "now": now(), "photoV": photos_cfg.get(mac.upper()),
            **zone_info(mac, r)}


# ============================================================================ droits

def visible_measures(acc):
    allowed = acc.get("allowed_measures")
    return list(allowed) if allowed else list(DEFAULT_MEASURES)


def rights(acc):
    vis = visible_measures(acc)
    return {"history": bool(acc["can_view_history"]), "live": bool(acc["can_live"]),
            "measures": vis if acc["can_live"] else [], "visible": vis,
            "alerts": bool(acc["can_receive_alerts"])}


def ring_payload(acc, with_live=True):
    mac = acc["mac"].upper()
    out = {"mac": mac, "key": topic_mac(mac).lower(), "label": acc["label"] or acc["ring_name"] or mac,
           "name": acc["ring_name"] or "", "model": acc["model"] or "", "rights": rights(acc),
           "notify": bool(acc["notify"])}
    if with_live:
        out["live"] = live_state(mac, acc)
    return out


# ============================================================================ authentification

def make_token(user):
    return signer.dumps({"u": int(user["id"]), "v": int(user["token_version"])})


def ok(**kw):
    return jsonify(dict(ok=True, **kw))


def fail(msg, code=400, **kw):
    return jsonify(dict(ok=False, error=str(msg), **kw)), code


def user_from_token(token):
    if not token:
        return None
    try:
        data = signer.loads(token, max_age=TOKEN_DAYS * 86400)
    except (BadSignature, SignatureExpired):
        return None
    user = clientdb.get_user(data.get("u"))
    if not user or not user["active"] or int(user["token_version"]) != int(data.get("v", -1)):
        return None
    return user


def auth_required(f):
    @wraps(f)
    def w(*a, **k):
        h = request.headers.get("Authorization", "")
        token = h[7:].strip() if h.lower().startswith("bearer ") else request.args.get("token")
        try:
            user = user_from_token(token)
        except Exception as e:
            return fail(f"Base indisponible : {e}", 503)
        if not user:
            return fail("Session expirée, reconnectez-vous", 401, reason="auth")
        g.user = user
        return f(*a, **k)
    return w


def access_for(mac):
    """Droits du compte connecté sur une bague (None si non affectée)."""
    for acc in clientdb.user_rings(g.user["id"]):
        if acc["mac"].upper() == mac:
            return acc
    return None


def user_json(u):
    return {"id": u["id"], "login": u["login"], "name": u["display_name"] or u["login"], "lang": u["lang"],
            "alertsEnabled": bool(u["alerts_enabled"]), "fcm": fcm.enabled}


# ============================================================================ API

@app.get("/api/client/health")
def health():
    t = now()
    with lock:
        seen = {m: {"statusAgo": t - ts, "online": gateway_online(rings[m]), "ring": rings[m]["ring"]}
                for m, ts in stats["statusSeen"].items() if m in rings}
    return ok(broker=mqttc.is_connected(), db=dbq.status().get("connected"), fcm=fcm.enabled, now=t,
              mqttUser=bool(MQTT_USER), prefix=PREFIX, messages=stats["messages"],
              lastMessageAgo=(t - stats["lastMessage"]) if stats["lastMessage"] else None,
              offlineAfter=OFFLINE_AFTER, rings=seen)


@app.post("/api/client/login")
def api_login():
    body = request.get_json(silent=True) or {}
    try:
        user, reason = clientdb.check_login(body.get("login"), body.get("password"))
    except Exception as e:
        log.exception("login")
        return fail(f"Base indisponible : {e}", 503)
    if not user:
        msg = {"locked": "Trop d'essais : réessayez dans 5 minutes",
               "disabled": "Compte désactivé, contactez l'administrateur"}.get(reason, "Identifiant ou mot de passe incorrect")
        return fail(msg, 401 if reason == "bad" else 403, reason=reason)
    log.info("Connexion de %s", user["login"])
    return ok(token=make_token(user), user=user_json(user))


@app.get("/api/client/me")
@auth_required
def api_me():
    return ok(user=user_json(g.user))


@app.post("/api/client/password")
@auth_required
def api_password():
    body = request.get_json(silent=True) or {}
    try:
        user = clientdb.change_password(g.user["id"], body.get("old"), body.get("new"))
    except PermissionError as e:
        return fail(e, 403)
    except ValueError as e:
        return fail(e)
    # Les autres téléphones sont déconnectés ; celui-ci reçoit un nouveau jeton
    return ok(token=make_token(user), user=user_json(user))


@app.post("/api/client/prefs")
@auth_required
def api_prefs():
    user = clientdb.set_prefs(g.user["id"], request.get_json(silent=True) or {})
    return ok(user=user_json(user))


@app.post("/api/client/device")
@auth_required
def api_device():
    body = request.get_json(silent=True) or {}
    token = (body.get("fcmToken") or "").strip()
    if not token:
        return fail("fcmToken manquant")
    clientdb.add_device(g.user["id"], token, body.get("platform"), body.get("appVersion"))
    return ok(fcm=fcm.enabled)


@app.post("/api/client/logout")
@auth_required
def api_logout():
    token = ((request.get_json(silent=True) or {}).get("fcmToken") or "").strip()
    if token:
        clientdb.remove_device(token)
    return ok()


@app.get("/api/client/rings")
@auth_required
def api_rings():
    return ok(rings=[ring_payload(a) for a in clientdb.user_rings(g.user["id"])], user=user_json(g.user))


@app.post("/api/client/rings/notify")
@auth_required
def api_notify_all():
    notify = bool((request.get_json(silent=True) or {}).get("notify"))
    clientdb.set_notify(g.user["id"], notify)
    return ok(notify=notify)


def ring_or_404(key):
    mac = mac_from_key(key)
    acc = access_for(mac) if mac else None
    return mac, acc


@app.get("/api/client/ring/<key>")
@auth_required
def api_ring(key):
    mac, acc = ring_or_404(key)
    if not acc:
        return fail("Bague non affectée à ce compte", 404)
    out = ring_payload(acc)
    # Valeurs en base si le service vient de démarrer et ne connaît pas encore la bague
    if not out["live"]["values"]:
        try:
            latest = dbq.latest_values(acc["ring_id"])
            vis = set(visible_measures(acc))
            out["live"]["values"] = {k: v for k, v in latest.items() if k in vis}
        except Exception:
            pass
    out["limits"] = LIMITS
    out["wearCheck"] = WEAR_CHECK_SECONDS
    return ok(ring=out)


@app.post("/api/client/ring/<key>/notify")
@auth_required
def api_notify(key):
    mac, acc = ring_or_404(key)
    if not acc:
        return fail("Bague non affectée à ce compte", 404)
    notify = bool((request.get_json(silent=True) or {}).get("notify"))
    clientdb.set_notify(g.user["id"], notify, mac)
    return ok(notify=notify)


def ring_ready(mac, allow_out=False):
    """(état, erreur) : la Gateway RHM doit être en ligne et la bague connectée
    (allow_out : Gateway Linux, « Actualiser » retente même une bague marquée hors portée)."""
    with lock:
        r = rings.get(mac)
        state = json.loads(json.dumps(r, default=str)) if r else None
    if not state or not state["statusTs"]:
        return None, fail("Aucune Gateway RHM ne signale cette bague", 409, reason="unknown")
    if state["ring"] == "unbound":
        return None, fail("Bague dissociée de la Gateway RHM", 409, reason="ring_unbound")
    if not gateway_online(state):
        return None, fail("Gateway RHM hors ligne (éteinte ou sans internet)", 409, reason="gateway_offline")
    if state["ring"] != "connected" and not (allow_out and state.get("gatewayType") == "linux"):
        return None, fail("Bague hors portée", 409, reason="ring_disconnected")
    return state, None


def app_req(login, via="p"):
    """reqId des demandes de Client RHM : « app-<login>-<p|r><hasard> ».
    p = mesure lancée par un bouton (« 📱 prise »), r = « Actualiser l'état » (« 📱 actualisée »).
    La GATEWAY RHM et l'admin lisent ce reqId pour afficher l'origine."""
    safe = re.sub(r"[^A-Za-z0-9_.]", "", login or "")[:24]
    return f"app-{safe}-{via}{uuid.uuid4().hex[:7]}" if safe else "app-" + uuid.uuid4().hex[:8]


def strip_sub(req):
    """« app-wissem-p123-spo2 » → « app-wissem-p123 » : 2e valeur d'une même connexion (script de mesure)."""
    return re.sub(r"-(hr|spo2|temp|hrv|battery|bat|all|reach)$", "", req or "")


def phone_by(req):
    """Login du compte Client RHM d'après le reqId, « * » si ancien format, "" si pas du téléphone."""
    if not isinstance(req, str) or not req.startswith("app-"):
        return ""
    req = strip_sub(req)
    parts = req.split("-")
    return "-".join(parts[1:-1]) if len(parts) >= 3 else "*"


def who_label(req):
    """Qui a lancé une mesure, pour « Patientez : … » : compte Client RHM, admin, Telegram…"""
    by = phone_by(req)
    if by and by != "*":
        return by
    req = str(req or "")
    return ("le Client RHM" if by else "l'admin" if req.startswith("adm-") else "Telegram" if req.startswith("tg-")
            else "la Web App" if req.startswith("web-") else "la gateway")


def phone_via(req):
    """« r » si la demande vient d'« Actualiser l'état », « p » pour une mesure lancée par un bouton."""
    if not phone_by(req):
        return ""
    return "r" if strip_sub(req).rsplit("-", 1)[-1].startswith("r") else "p"


# ---------------------------------------------------------------------------- localisation (Gateway Linux)
LOCATION_TTL = int(os.getenv("LOCATION_TTL_SECONDS", "120"))   # localisation réutilisée pendant ce délai
REACH_WAIT = int(os.getenv("REACH_WAIT_SECONDS", "10"))        # attente max de la réponse d'une gateway
# Cycle permanent : test de portée gateway après gateway, pour chaque bague Linux ; la meilleure (RSSI)
# = position, mise à jour en direct dans le Client RHM. Pause entre deux cycles (0 = cycle désactivé).
REACH_CYCLE_PAUSE = int(os.getenv("REACH_CYCLE_SECONDS", "10"))
# Tour de rôle : toutes les Pi des zones de la bague à chaque tour, meilleur RSSI (+3 dB pièce actuelle).
# 0 = tour continu (pause REACH_CYCLE_SECONDS entre deux tours complets)
REACH_EVERY = int(os.getenv("REACH_EVERY_SECONDS", "0"))
reach_waiters = {}   # reqId → queue (réponse du test de portée)
routes = {}          # reqId de mesure → {"cmd", "order": [gateways], "i"}
locating = {}        # mac → threading.Event (localisation en cours)


def linux_gateways(mac):
    """Gateway Linux en ligne qui gèrent cette bague (noms tels qu'utilisés dans les commandes)."""
    out, seen = [], set()
    with lock:
        for gw in gateways.values():
            if id(gw) in seen:
                continue
            seen.add(id(gw))
            if gw.get("online") and gw.get("type") == "linux" and (
                    (gw.get("ringMac") or "").upper() == mac.upper() or mac.upper() in (gw.get("rings") or {})):
                out.append(gw["name"])
    return sorted(set(out))


# ---------------------------------------------------------------------------- localisation par écoute passive
# Gateway multi-bagues : chaque Pi écoute en continu les bagues de ses zones et publie
# eis/colmi/gateway/<nom>/presence toutes les ~5 s. La bague est là où le RSSI est le meilleur
# (zone principale favorisée), mise à jour en temps réel, sans test de portée à tour de rôle.
SEEN_FRESH = int(os.getenv("SEEN_FRESH_SECONDS", "15"))            # entendue il y a ≤ 15 s = « détectée »
SEEN_FRESH_BUSY = int(os.getenv("SEEN_FRESH_BUSY_SECONDS", "180"))  # gateway occupée (écoute en pause)
ZONE_MAIN_BONUS = int(os.getenv("ZONE_MAIN_BONUS_DB", "5"))         # zone principale : +5 dB
STAY_BONUS = int(os.getenv("LOCATION_STAY_BONUS_DB", "3"))          # anti-clignotement : +3 dB pour la zone actuelle
HANDOFF_MIN_RSSI = int(os.getenv("HANDOFF_MIN_RSSI", "-90"))        # autre zone acceptée si gateway occupée
MISS_WINDOWS = int(os.getenv("SEEN_MISS_WINDOWS", "2"))             # 2 écoutes sans elle : plus « dans » cette pièce
# « Hors portée » : décidé UNIQUEMENT par test_reachable_v1.py. Bague plus entendue par l'écoute passive
# depuis CONFIRM_AFTER s (ou mesure en échec « bague non jointe ») → test de portée demandé à toutes les Pi
# de ses zones ; aucune ne l'entend CONFIRM_TRIES fois de suite → hors portée.
CONFIRM_AFTER = int(os.getenv("CONFIRM_AFTER_SECONDS", "60"))
CONFIRM_TRIES = int(os.getenv("CONFIRM_TRIES", "3"))
# Après CONFIRM_RESTART_AFTER tests ratés : redémarrage du service sur les Pi qui ne l'entendent pas, puis
# dernier test. btrestart = service Bluetooth (rapide) ; restart = service gateway-rhm complet.
CONFIRM_RESTART_AFTER = int(os.getenv("CONFIRM_RESTART_AFTER", "2"))
CONFIRM_RESTART_CMD = os.getenv("CONFIRM_RESTART_CMD", "btrestart")
CONFIRM_RESTART_WAIT = int(os.getenv("CONFIRM_RESTART_WAIT_SECONDS", "25"))
CONFIRM_RESTART_COOLDOWN = int(os.getenv("CONFIRM_RESTART_COOLDOWN_SECONDS", "600"))   # 1 fois / 10 min / Pi
gw_restarted = {}     # gateway → heure du dernier redémarrage automatique
CONFIRM_RETRY = int(os.getenv("CONFIRM_RETRY_SECONDS", "30"))
CONFIRM_WAIT = int(os.getenv("CONFIRM_WAIT_SECONDS", "40"))       # réponse max. d'une Pi (test + attente Bluetooth)
confirm = {}          # mac → {"running", "fails", "last", "absent"}
SCANNER_ALIVE = 30
presence = {}        # mac → gateway → {"rssi", "ts", "role"}
presence_gw = {}     # gateway → heure du dernier message presence


def on_presence(gw, p):
    t = now()
    presence_gw[gw] = t
    macs = []
    with lock:
        g = gateways.get(gw)
        if g is not None and isinstance(p.get("busy"), (dict, type(None))):
            g["busy"] = p.get("busy")
    for x in p.get("rings") or []:
        mac = str((x or {}).get("mac") or "").upper()
        if not mac:
            continue
        macs.append(mac)
        e = presence.setdefault(mac, {}).setdefault(gw, {"rssi": None, "ts": 0})
        e["role"] = x.get("role")
        v = (p.get("seen") or {}).get(mac)
        if v and v.get("rssi") is not None:
            e.update(rssi=v["rssi"], ts=t, misses=0)
        elif not p.get("partial"):
            e["misses"] = e.get("misses", 0) + 1     # fenêtre d'écoute complète sans la bague
    for mac in macs:
        locate_scan(mac)


POST_MEASURE_GRACE = int(os.getenv("POST_MEASURE_GRACE_SECONDS", "20"))


def seen_by_measure(mac, gw):
    """Une mesure (en cours ou réussie) prouve que la bague est là : « entendue à l'instant ».
    Évite le faux « déconnectée » juste après une mesure : écoute passive en pause pendant la connexion,
    puis Bluetooth redémarré et bague qui se réannonce quelques secondes plus tard."""
    e = presence.get(mac.upper())
    if e is None or gw not in e:
        return
    t = now()
    e[gw].update(ts=t, misses=0, graceUntil=t + POST_MEASURE_GRACE)


def confirm_reach(mac, why):
    """Test de portée réel (test_reachable_v1.py) sur toutes les Pi des zones de la bague, en même temps."""
    c = confirm.setdefault(mac, {"running": False, "fails": 0, "last": 0, "absent": False})
    if c["running"]:
        return
    c.update(running=True, last=now())
    again = False
    try:
        names = linux_gateways(mac)
        if not names:
            return
        log.info("Bague %s : %s → test de portée sur %s", mac, why, ", ".join(names))
        waits = {}
        for gw in names:
            req = f"srv-chk-{uuid.uuid4().hex[:8]}"
            waits[gw] = reach_waiters[req] = queue.Queue()
            waits[gw].req = req
            mqttc.publish(f"{PREFIX}/{topic_mac(mac)}/cmd",
                          json.dumps({"cmd": "reach", "reqId": req, "gateway": gw, "force": True}), qos=1)
        heard, uncertain, deadline = [], [], time.time() + CONFIRM_WAIT
        for gw, q in waits.items():
            try:
                p = q.get(timeout=max(0.1, deadline - time.time()))
            except queue.Empty:
                p = {"status": "error", "error": "no_answer"}
            reach_waiters.pop(q.req, None)
            if p.get("status") == "ok":
                heard.append((gw, p.get("rssi")))
            elif p.get("error") in ("cancelled", "no_answer", "measure_failed", "busy"):
                uncertain.append(gw)        # test interrompu (mesure) / pas de réponse : pas une preuve
        if heard:
            c.update(fails=0, absent=False)
            log.info("Bague %s entendue par test_reachable : %s", mac,
                     ", ".join(f"{g} ({r} dBm)" for g, r in heard))
        elif uncertain and len(uncertain) == len(names):
            log.info("Bague %s : test de portée non concluant (%s)", mac, ", ".join(uncertain))
        else:
            c["fails"] += 1
            log.info("Bague %s non entendue par test_reachable (%d/%d)", mac, c["fails"], CONFIRM_TRIES)
            if c["fails"] >= CONFIRM_TRIES:
                c["absent"] = True
                log.warning("Bague %s hors portée (%d tests ratés, service redémarré)", mac, c["fails"])
            elif c["fails"] == CONFIRM_RESTART_AFTER:
                # 2 tests ratés : on redémarre le service des Pi qui ne l'entendent pas, puis 3e test tout de suite
                done = []
                for gw in names:
                    if gw in uncertain or now() - gw_restarted.get(gw, 0) < CONFIRM_RESTART_COOLDOWN:
                        continue
                    gw_restarted[gw] = now()
                    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", gw)
                    mqttc.publish(f"{PREFIX}/gateway/{safe}/cmd", json.dumps(
                        {"cmd": CONFIRM_RESTART_CMD, "reqId": f"srv-rst-{uuid.uuid4().hex[:8]}"}), qos=1)
                    done.append(gw)
                if done:
                    log.warning("Bague %s : %d tests ratés → %s sur %s, puis dernier test", mac, c["fails"],
                                CONFIRM_RESTART_CMD, ", ".join(done))
                    time.sleep(CONFIRM_RESTART_WAIT)
                again = True                             # dernier test tout de suite
        locate_scan(mac, force=True)
    except Exception:
        log.exception("test de portée %s", mac)
    finally:
        c.update(running=False, last=now())
    if again:
        confirm_reach(mac, "dernier test après redémarrage")


def confirm_check(mac):
    """Cycle : bague plus entendue par l'écoute passive depuis CONFIRM_AFTER s → test de portée."""
    c = confirm.get(mac) or {}
    if c.get("running") or c.get("absent") and now() - (c.get("last") or 0) < 300:
        return
    with lock:
        r = rings.get(mac) or {}
        busy = any(k in MEASURES or k in ("steps", "reach") for k in (r.get("pending") or {}))
    if busy:
        return
    last_seen = max([(presence.get(mac) or {}).get(g, {}).get("ts") or 0 for g in linux_gateways(mac)] or [0])
    if now() - last_seen < CONFIRM_AFTER or now() - (c.get("last") or 0) < CONFIRM_RETRY:
        return
    threading.Thread(target=confirm_reach, args=(mac, f"non entendue depuis {now() - last_seen} s"),
                     daemon=True).start()


def gw_busy(name):
    with lock:
        for g in gateways.values():
            if g.get("name") == name:
                return g.get("busy")
    return None


def scan_mode(mac):
    """Toutes les gateways Linux de cette bague font l'écoute passive (gateway_multi.py) ?"""
    names = linux_gateways(mac)
    if not names:
        return False
    t = now()
    with lock:
        multi = {g["name"] for g in gateways.values() if g.get("multi")}
    return all(n in multi and t - presence_gw.get(n, 0) < SCANNER_ALIVE for n in names)


def locate_scan(mac, force=False):
    """Localisation d'après l'écoute passive. Publie eis/colmi/<MAC>/location (retenue) si elle change."""
    t = now()
    names = linux_gateways(mac)
    ranking = []
    for gw in names:
        e = (presence.get(mac) or {}).get(gw) or {}
        b = gw_busy(gw)
        mine = bool(b and str(b.get("mac") or "").upper() == mac)
        age = t - (e.get("ts") or 0)
        heard = mine or (e.get("rssi") is not None and (
            t <= (e.get("graceUntil") or 0)          # juste après une mesure : délai de grâce
            or (age <= (SEEN_FRESH_BUSY if b else SEEN_FRESH) and e.get("misses", 0) < MISS_WINDOWS)))
        cf = confirm.get(mac) or {}
        recent = heard or (e.get("rssi") is not None and not cf.get("absent"))
        ranking.append({"gateway": gw, "reachable": heard, "rssi": e.get("rssi") if heard else None,
                        "role": e.get("role"), "busy": (b or {}).get("cmd") if mine else None,
                        "occupied": bool(b) and not mine, "seenAgo": age if e.get("ts") else None,
                        "recent": recent, "lastRssi": e.get("rssi")})
    with lock:
        r = rings.setdefault(mac, new_ring(mac))
        old = r.get("location") or {}
    prev = old.get("gateway")

    def score(x):
        if x.get("busy"):
            return 1000                                   # connectée à cette gateway (mesure en cours)
        return (x["rssi"] if x["rssi"] is not None else -999) + (ZONE_MAIN_BONUS if x.get("role") == "main" else 0) \
            + (STAY_BONUS if x["gateway"] == prev else 0)
    heard = sorted([x for x in ranking if x["reachable"]], key=score, reverse=True)
    last_seen = max([(presence.get(mac) or {}).get(g, {}).get("ts") or 0 for g in names] or [0]) or None
    best = heard[0] if heard else None
    if best and (confirm.get(mac) or {}).get("absent"):
        confirm[mac].update(absent=False, fails=0)          # de nouveau entendue
        log.info("Bague %s de nouveau entendue (« %s »)", mac, best["gateway"])
    # Pas entendue à l'instant : tant que test_reachable n'a pas dit « hors portée », la bague est toujours là
    # (trou d'annonce, connexion, redémarrage Bluetooth…) → on garde sa pièce, sans « déconnectée »
    recent = sorted([x for x in ranking if x["recent"] and not x["reachable"]],
                    key=lambda x: (0 if x["gateway"] == prev else 1, x["seenAgo"] if x["seenAgo"] is not None else 1e9))
    kept = None if best else (recent[0] if recent else None)
    if kept:
        kept = dict(kept, rssi=kept.get("lastRssi"))
    top = best or kept
    # Non entendue du tout : on ne garde l'ancienne gateway que si elle est encore en ligne et suit cette bague
    # (sinon une Pi éteinte resterait « propriétaire » et les autres resteraient en veille)
    loc = {"gateway": top["gateway"] if top else (prev if prev in names else None), "reachable": bool(top),
           "rssi": top["rssi"] if top else None, "zoneRole": top.get("role") if top else None,
           "ranking": ranking, "order": [x["gateway"] for x in heard] + [x["gateway"] for x in recent],
           "ts": t, "seenTs": last_seen, "mode": "scan", "kept": bool(kept)}
    changed = (old.get("gateway") != loc["gateway"] or bool(old.get("reachable")) != loc["reachable"]
               or old.get("order") != loc["order"] or old.get("mode") != "scan")
    if not (changed or force or t - (old.get("ts") or 0) >= 30):
        with lock:
            r["location"].update(rssi=loc["rssi"], ranking=ranking, seenTs=last_seen)   # RSSI à jour, sans publier
            push = t - (r.get("_pushLoc") or 0) >= 5
            if push:
                r["_pushLoc"] = t
        if push:
            push_ring(mac)      # « Dernière détection : il y a 2 s » à jour dans l'app
        return r["location"]
    mqttc.publish(f"{PREFIX}/{topic_mac(mac)}/location", json.dumps(loc), qos=1, retain=True)
    with lock:
        r["location"] = loc
        if best:
            r["gateway"] = r["lastZoneGw"] = loc["gateway"]
    if changed and (old.get("gateway") != loc["gateway"] or bool(old.get("reachable")) != loc["reachable"]):
        log.info("Bague %s : %s", mac, f"zone « {loc['gateway']} » ({loc['rssi']} dBm"
                 + (", principale" if loc["zoneRole"] == "main" else "") + ")" if top
                 else "hors portée (confirmé par test_reachable)")
    push_ring(mac)
    return loc


def locate(mac, login=None):
    """Test de portée demandé aux gateways Linux À TOUR DE RÔLE ; la meilleure (RSSI) = position de la bague.
    Publie eis/colmi/<MAC>/location (retenu) et renvoie la localisation."""
    if scan_mode(mac):
        return locate_scan(mac, force=True)          # écoute passive : localisation immédiate
    ev = locating.get(mac)
    if ev and not ev.is_set():
        ev.wait(REACH_WAIT * 6)                      # une localisation est déjà en cours : on attend son résultat
        with lock:
            return (rings.get(mac) or {}).get("location")
    ev = locating[mac] = threading.Event()
    try:
        with lock:
            prev = ((rings.get(mac) or {}).get("location") or {}).get("gateway")
        names = linux_gateways(mac)
        # Seulement les Pi des zones de la bague : dernière Pi qui l'a entendue → zone principale → secondaires
        z = zones_cfg["rings"].get(mac.upper()) or {}
        zone_gws = [g2 for g2 in [z.get("main")] + list(z.get("secondary") or []) if g2]
        if zone_gws:
            names = [g2 for g2 in names if g2 in zone_gws]
            names.sort(key=lambda g2: zone_gws.index(g2))
        order = ([prev] if prev in names else []) + [n for n in names if n != prev]
        ranking = []
        for gw in order:
            req = app_req(login, "r") if login else f"srv-loc-{uuid.uuid4().hex[:8]}"
            q = reach_waiters[req] = queue.Queue()
            mqttc.publish(f"{PREFIX}/{topic_mac(mac)}/cmd", json.dumps({"cmd": "reach", "reqId": req, "gateway": gw}), qos=1)
            try:
                p = q.get(timeout=REACH_WAIT)
            except queue.Empty:
                p = {"status": "error", "error": "no_answer"}
            reach_waiters.pop(req, None)
            ok_ = p.get("status") == "ok"
            ranking.append({"gateway": gw, "reachable": ok_, "rssi": p.get("rssi") if ok_ else None,
                            "busy": p.get("busy") if ok_ else None,
                            "error": None if ok_ else p.get("error")})
            (log.info if login else log.debug)("Localisation %s : « %s » → %s", mac, gw,
                                               f"RSSI {p.get('rssi')} dBm" if ok_ else p.get("error"))
        # Gateway occupée avec la bague (connectée) d'abord, puis le meilleur RSSI
        # Gateway occupée avec la bague (connectée) d'abord, puis le meilleur RSSI (+3 dB pour la pièce actuelle)
        heard = sorted([x for x in ranking if x["reachable"]],
                       key=lambda x: (0 if x.get("busy") else 1,
                                      -((x["rssi"] if x["rssi"] is not None else -999)
                                        + (STAY_BONUS if x["gateway"] == prev else 0))))
        if not heard:
            with lock:
                r0 = rings.get(mac) or {}
                busy_now = any(k != "reach" for k in (r0.get("pending") or {}))
                prev_loc = r0.get("location")
            silent = [x["gateway"] for x in ranking if x.get("error") in ("no_answer", "cancelled", "measure_failed")]
            if prev_loc and (busy_now or silent):
                # Résultat incertain (gateway muette / mesure en cours) : on garde la localisation précédente
                log.info("Localisation %s incertaine (%s) : localisation précédente gardée", mac,
                         "mesure en cours" if busy_now else "pas de réponse de " + ", ".join(silent))
                return prev_loc
        with lock:
            old0 = (rings.get(mac) or {}).get("location") or {}
        loc = {"gateway": heard[0]["gateway"] if heard else (prev if prev in names else None), "reachable": bool(heard),
               "rssi": heard[0]["rssi"] if heard else None, "ranking": ranking,
               "order": [x["gateway"] for x in heard], "ts": now(),
               # Dernière détection : Pi qui l'a entendue + heure (gardées quand elle n'est plus entendue)
               "seenTs": now() if heard else old0.get("seenTs"),
               "seenGateway": heard[0]["gateway"] if heard else old0.get("seenGateway") or old0.get("gateway")}
        # Pi précédente : celle où la bague était entendue AVANT de passer sur la nouvelle (+ heure)
        before = old0.get("seenGateway") or (old0.get("gateway") if old0.get("reachable") else None)
        if heard and before and before != loc["seenGateway"]:
            loc["prevGateway"], loc["prevTs"] = before, old0.get("seenTs") or old0.get("ts")
        else:
            loc["prevGateway"], loc["prevTs"] = old0.get("prevGateway"), old0.get("prevTs")
        mqttc.publish(f"{PREFIX}/{topic_mac(mac)}/location", json.dumps(loc), qos=1, retain=True)
        with lock:
            r = rings.setdefault(mac, new_ring(mac))
            old = r.get("location") or {}
            r["location"] = loc
            if heard:
                r["gateway"] = r["lastZoneGw"] = loc["gateway"]   # « via » = gateway où la bague est localisée
            # L'état de la bague vient du test de portée (pas d'un minuteur)
            r["gatewayType"] = "linux"
            r["online"] = True
            r["statusTs"] = now()
            if r["ring"] != "unbound":
                r["ring"] = "connected" if heard else "disconnected"
                if heard:
                    r["outTs"] = 0
                else:
                    r["outTs"] = r.get("outTs") or now()
            snap = json.loads(json.dumps(r, default=str))
        alerts.observe(mac, snap)
        if login or old.get("gateway") != loc["gateway"] or bool(old.get("reachable")) != loc["reachable"]:
            log.info("Bague %s localisée : %s", mac, f"« {loc['gateway']} » ({loc['rssi']} dBm)" if heard else "hors portée")
        push_ring(mac)   # mise à jour en direct dans le Client RHM
        return loc
    finally:
        ev.set()


def reach_cycle():
    """Cycle permanent de localisation (bagues des Gateway Linux), une gateway à la fois."""
    time.sleep(15)   # laisse arriver les statuts des gateways après le démarrage
    while True:
        try:
            macs = set()
            with lock:
                for gw in gateways.values():
                    if gw.get("online") and gw.get("type") == "linux" and gw.get("ringMac"):
                        macs.add(gw["ringMac"].upper())
                    if gw.get("online") and gw.get("type") == "linux":
                        macs.update(gw.get("rings") or {})
            for mac in sorted(macs):
                if scan_mode(mac):
                    locate_scan(mac)     # écoute passive : pièce actuelle
                    confirm_check(mac)   # plus entendue depuis 60 s → test_reachable
                    continue
                with lock:
                    r = rings.get(mac) or {}
                    busy = list(r.get("pending", {}))   # mesure, batterie, pas… en cours : on ne dérange pas
                    on_tv = r.get("gatewayType") == "android" and gateway_online(r) and r.get("ring") != "unbound"
                with lock:
                    last_loc = (r.get("location") or {}).get("ts") or 0
                if busy or on_tv or now() - last_loc < REACH_EVERY:
                    # mesure en cours (on ne la dérange pas) / bague tenue par une TV Android (priorité Android :
                    # les Gateway Linux sont en veille, pas de localisation)
                    continue
                locate(mac)
        except Exception:
            log.exception("cycle de localisation")
        time.sleep(max(1, REACH_CYCLE_PAUSE))


def fresh_location(mac):
    with lock:
        loc = (rings.get(mac) or {}).get("location")
    if loc and loc.get("reachable") and loc.get("order") and now() - (loc.get("ts") or 0) < LOCATION_TTL:
        return loc
    return None


def send_located(mac, cmd, req, loc):
    """Envoie la commande à la meilleure gateway ; en cas d'échec, handle_result passe à la suivante."""
    order = list(loc["order"])
    if loc.get("mode") == "scan" and len(order) > 1:
        # Gateway au meilleur RSSI occupée avec une AUTRE bague : une autre zone qui l'entend bien mesure
        b = gw_busy(order[0])
        if b and str(b.get("mac") or "").upper() != mac.upper():
            rssi = {x["gateway"]: x.get("rssi") for x in loc.get("ranking") or []}
            alt = [g2 for g2 in order[1:] if not gw_busy(g2) and (rssi.get(g2) or -999) >= HANDOFF_MIN_RSSI]
            if alt:
                log.info("Mesure %s (%s) : « %s » occupée (%s %s) → « %s » (%s dBm)", cmd, req, order[0],
                         b.get("cmd"), b.get("mac"), alt[0], rssi.get(alt[0]))
                order = [alt[0]] + [g2 for g2 in order if g2 != alt[0]]
    handoff = order[0] != loc["order"][0]
    # La mesure se fait UNIQUEMENT sur la Pi choisie (3 essais sur cette Pi, Bluetooth redémarré au 3ᵉ) :
    # pas de relais vers une autre gateway
    order = order[:1]
    routes[req] = {"cmd": cmd, "order": order, "i": 0}
    # Pas d'autre zone libre : la mesure attend son tour sur ce Pi → on dit qui l'occupe
    wait = None
    b = gw_busy(order[0]) if loc.get("mode") == "scan" else None
    if b and str(b.get("mac") or "").upper() != mac.upper():
        bm = str(b.get("mac") or "").upper()
        with lock:
            other = rings.get(bm) or {}
            zone = order[0]
        wait = {"gateway": zone, "cmd": b.get("cmd"), "ringMac": bm, "ringName": other.get("name") or bm,
                "by": who_label(b.get("reqId")), "since": b.get("since")}
        wait["message"] = (f"Patientez : {wait['by']} a lancé une mesure {str(wait['cmd'] or '').upper()} "
                           f"({wait['ringName']}) sur la même gateway")
        with lock:
            pnd = (rings.get(mac) or {}).get("pending", {}).get(cmd)
            if pnd is not None:
                pnd["waitFor"] = wait
        log.info("Mesure %s (%s) en file sur « %s » : %s", cmd, req, order[0], wait["message"])
        push_ring(mac)
    # Une autre gateway peut prendre le relais → un seul essai Bluetooth sur la première
    publish_to_gateway(mac, order[0], {"cmd": cmd, "reqId": req, "gateway": order[0], "oneTry": len(order) > 1})
    log.info("Commande %s (%s) envoyée à « %s » (%s%s)", cmd, req, order[0],
             "autre zone, la meilleure est occupée" if handoff else "meilleur RSSI",
             ", topic gateway" if cmd in GW_TOPIC_CMDS else "")
    return order[0], wait


def is_linux_ring(mac):
    with lock:
        r = rings.get(mac) or {}
    return r.get("gatewayType") == "linux" and bool(linux_gateways(mac))


def send_cmd(mac, cmd, who, via="p", gateway=None, publish=True):
    """Même règle que l'admin : une seule mesure à la fois (même mesure = partagée, autre = refusée).
    gateway : nom de la gateway qui doit l'exécuter ; publish=False : seulement réservée (envoi plus tard)."""
    with lock:
        r = rings.setdefault(mac, new_ring(mac))
        if cmd in MEASURES:
            running = [k for k in r["pending"] if k in MEASURES]
            if running and cmd not in running:
                by = who_label(r["pending"][running[0]].get("reqId"))
                what = {"all": "HR + SpO2 + T° + HRV", "temp": "température", "health": "Health check",
                        "fatigue": "Fatigue", "stress": "Stress"}.get(running[0], running[0].upper())
                return {"ok": False, "error": f"Mesure {what} déjà en cours (lancée par {by})",
                        "busy": running[0], "by": by}, 409
            if cmd in running:
                return {"ok": True, "already": True, "reqId": r["pending"][cmd].get("reqId")}, 200
        req = app_req(g.user["login"], via)
        msg = {"cmd": cmd, "reqId": req}
        if gateway:
            msg["gateway"] = gateway
        info = publish_to_gateway(mac, gateway, msg) if publish else None
        r["pending"][cmd] = {"since": now(), "requested": now(), "reqId": req, "confirmed": False}
        r["errors"].pop(cmd, None)
    log.info("Commande %s envoyée à %s (%s)", cmd, mac, who)
    push_ring(mac)
    return {"ok": True, "sent": (info.rc == mqtt.MQTT_ERR_SUCCESS) if info else None, "reqId": req}, 200


# ---------------------------------------------------------------------------- « Patientez » : bague occupée
# Un 2ᵉ compte lance une mesure pendant celle d'un autre : il est noté ; à la fin de la mesure en cours, il
# reçoit « bague libre » (flux de l'app + notification) et l'app lui propose de lancer sa mesure (Oui / Non).
WAIT_MAX = int(os.getenv("WAIT_FREE_MAX_SECONDS", "600"))
waiters = {}          # mac → {user_id: {"cmd", "since", "by"}}


FREE_UNITS = {"hr": "bpm", "spo2": "%", "temp": "°C", "hrv": "ms", "stress": "/100", "fatigue": "", "health": "",
              "steps": "pas", "bp": "mmHg"}
FREE_LABELS = {"hr": "HR", "spo2": "SpO2", "temp": "T°", "hrv": "HRV", "stress": "Stress", "fatigue": "Fatigue",
               "health": "Health check", "steps": "Pas", "bp": "Tension"}


def finished_result(r, since):
    """Résultat de la mesure qui vient de finir (valeurs reçues depuis `since`), pour la popup « Bague libre »."""
    vals, errs, last = {}, {}, 0
    for k in FREE_LABELS:
        v = (r.get("values") or {}).get(k) or {}
        if (v.get("ts") or 0) >= since:
            d = v.get("data") or {}
            val = f"{d.get('sbp')}/{d.get('dbp')}" if k == "bp" and d.get("sbp") else d.get("steps") if k == "steps" \
                else d.get("value")
            if val is not None:
                vals[k] = val
                last = max(last, v.get("ts") or 0)
        e = (r.get("errors") or {}).get(k) or {}
        if (e.get("ts") or 0) >= since and k not in vals:
            errs[k] = e.get("code")
    text = " · ".join(f"{FREE_LABELS[k]} {v} {FREE_UNITS[k]}".strip() for k, v in vals.items())
    return {"values": vals, "errors": errs, "ts": last or None, "text": text}


def notify_free(mac):
    with lock:
        w = waiters.pop(mac, {})
        r = rings.get(mac) or {}
        name = r.get("name") or mac
    t = now()
    w = {uid: x for uid, x in w.items() if t - x["since"] <= WAIT_MAX}
    if not w:
        return
    with lock:
        # Valeurs de la mesure qui vient de finir (pas un ancien relevé)
        res_ = finished_result(r, min(x["since"] for x in w.values()) - 300)
    log.info("Bague %s libre : %d compte(s) prévenu(s) · %s", mac, len(w), res_["text"] or "pas de valeur")
    for uid, x in w.items():
        push_user(uid, {"type": "measure_free", "mac": mac, "cmd": x["cmd"], "by": x["by"], "ts": t, "result": res_})
    if fcm.enabled:
        try:
            for d in clientdb.device_tokens(list(w)):
                x = w[d["user_id"]]
                body = (f"{name} : mesure terminée" + (f" ({x['by']})" if x.get("by") else "")
                        + (f" — {res_['text']}" if res_["text"] else "")
                        + ". La bague est libre : lancer votre mesure ?")
                res = fcm.send(d["fcm_token"], "✅ Bague libre", body,
                               {"mac": mac, "kind": "measure_free", "cmd": x["cmd"], "by": x.get("by") or "",
                                "result": json.dumps(res_)})
                if res is False:
                    clientdb.remove_device(d["fcm_token"])
        except Exception:
            log.exception("notification bague libre")


@app.post("/api/client/ring/<key>/cmd")
@auth_required
def api_cmd(key):
    resp = _api_cmd(key)
    body, code = (resp if isinstance(resp, tuple) else (resp, 200))
    if code == 409:
        data = body.get_json(silent=True) or {}
        if data.get("busy"):
            mac, _ = ring_or_404(key)
            cmd = (request.get_json(silent=True) or {}).get("cmd")
            with lock:
                waiters.setdefault(mac, {})[g.user["id"]] = {"cmd": cmd, "since": now(), "by": data.get("by")}
            log.info("%s attend la fin de la mesure %s sur %s", g.user["login"], data["busy"], mac)
            data.update(waiting=True, message=f"{data.get('error')} — patientez : vous serez prévenu à la fin.")
            return jsonify(data), 409
    return resp


def _api_cmd(key):
    mac, acc = ring_or_404(key)
    if not acc:
        return fail("Bague non affectée à ce compte", 404)
    cmd = (request.get_json(silent=True) or {}).get("cmd")
    if cmd == "sleep":
        # « Récupérer le sommeil de la bague » (historique du sommeil)
        if not rights(acc)["history"]:
            return fail("Historique non autorisé", 403)
        if is_linux_ring(mac):
            return fail("Récupération du sommeil pas encore disponible sur une Gateway Linux", 409,
                        reason="not_supported")
        _, err = ring_ready(mac)
        if err:
            return err
        mqttc.publish(f"{PREFIX}/{topic_mac(mac)}/cmd",
                      json.dumps({"cmd": "sleep", "reqId": app_req(g.user["login"])}), qos=1)
        log.info("Récupération du sommeil demandée pour %s (%s)", mac, g.user["login"])
        return ok(cmd="sleep", started=now())
    allowed = rights(acc)["measures"]
    # « MESURER HR + SpO2 » (une seule connexion) : autorisé si HR et SpO2 le sont
    if cmd != "battery" and cmd not in allowed and not (cmd == "all" and {"hr", "spo2"} <= set(allowed)):
        return fail("Mesure non autorisée", 403)
    _, err = ring_ready(mac, allow_out=True)   # Gateway Linux : la mesure elle-même revérifie la bague
    if err:
        return err
    if is_linux_ring(mac):
        return linux_measure(mac, cmd)
    if cmd == "battery":
        # Batterie : toujours autorisée, réponse rapide (pas de mesure en cours à suivre)
        mqttc.publish(f"{PREFIX}/{topic_mac(mac)}/cmd",
                      json.dumps({"cmd": "battery", "reqId": app_req(g.user["login"])}), qos=1)
        log.info("Commande battery envoyée à %s (%s)", mac, g.user["login"])
        return ok(cmd="battery")
    res, code = send_cmd(mac, cmd, g.user["login"])
    return jsonify(res), code


def linux_measure(mac, cmd):
    """Gateway Linux : la mesure part directement sur la gateway au meilleur RSSI (localisation récente),
    sinon localisation à tour de rôle d'abord."""
    login = g.user["login"]
    if cmd == "battery":
        req = app_req(login)
    else:
        res, code = send_cmd(mac, cmd, login, publish=False)
        if not res.get("ok") or res.get("already"):
            return jsonify(res), code
        req = res["reqId"]
    loc = fresh_location(mac)
    if loc:
        gw, wait = send_located(mac, cmd, req, loc)
        return ok(cmd=cmd, reqId=req, gateway=gw, waitFor=wait, message=(wait or {}).get("message"))

    def run():
        loc2 = locate(mac, login)
        if loc2 and loc2.get("reachable") and loc2.get("order"):
            send_located(mac, cmd, req, loc2)
            return
        with lock:
            r = rings.setdefault(mac, new_ring(mac))
            r["pending"].pop(cmd, None)
            r["errors"][cmd] = {"ts": now(), "code": "ring_disconnected", "dur": None}
        push_ring(mac)
    threading.Thread(target=run, daemon=True).start()
    return ok(cmd=cmd, reqId=req, locating=True)


@app.get("/api/client/ring/<key>/photo")
@auth_required
def api_photo(key):
    """Photo du résident (envoyée par l'admin) ; l'app la recharge quand photoV change."""
    mac, acc = ring_or_404(key)
    if not acc:
        return fail("Bague non affectée à ce compte", 404)
    p = photos.path_for(mac)
    if not os.path.exists(p):
        return fail("Pas de photo", 404)
    return send_file(p, mimetype="image/jpeg", max_age=86400)


@app.post("/api/client/ring/<key>/cancel")
@auth_required
def api_cancel(key):
    """« Annuler la mesure » : la gateway arrête la mesure en cours de cette bague (et celles en file)."""
    mac, acc = ring_or_404(key)
    if not acc or not rights(acc)["measures"]:
        return fail("Bague non affectée à ce compte", 404)
    with lock:
        r = rings.setdefault(mac, new_ring(mac))
        running = [k for k in r["pending"] if k in MEASURES or k == "steps"]
        loc = r.get("location") or {}
        for k in running:
            r["pending"].pop(k, None)
            r["errors"][k] = {"ts": now(), "code": "cancelled", "dur": None}
        gws = list(dict.fromkeys([x for x in [loc.get("gateway")] + [rt["order"][rt["i"]] for rt in routes.values()
                                                                      if rt.get("cmd") in running] if x]))
    msg = {"cmd": "cancel", "reqId": app_req(g.user["login"]), "mac": mac}
    if is_linux_ring(mac) and gws:
        for gw in gws:   # gateway qui mesure (et celle où la bague est localisée)
            mqttc.publish(f"{PREFIX}/{topic_mac(mac)}/cmd", json.dumps(dict(msg, gateway=gw)), qos=1)
    else:
        mqttc.publish(f"{PREFIX}/{topic_mac(mac)}/cmd", json.dumps(msg), qos=1)
    log.info("Mesure annulée sur %s par %s (%s)", mac, g.user["login"], ", ".join(running) or "rien en cours")
    push_ring(mac)
    if waiters.get(mac):
        notify_free(mac)
    return ok(cancelled=running)


@app.post("/api/client/ring/<key>/check")
@auth_required
def api_check(key):
    """« Actualiser l'état » : une mesure HR sert de test de port (15 s sans problème = portée).
    Si une mesure tourne déjà : busy (l'app fait patienter puis relance à la fin)."""
    mac, acc = ring_or_404(key)
    if not acc:
        return fail("Bague non affectée à ce compte", 404)
    state, err = ring_ready(mac, allow_out=True)
    if err:
        return err
    running = [k for k in state["pending"] if k in MEASURES]
    if running:
        return ok(busy=running[0], since=state["pending"][running[0]].get("since"))
    if state.get("gatewayType") == "linux" and linux_gateways(mac):
        # Gateway Linux : localisation = test de portée (test_reachable_v1.py) à tour de rôle
        login = g.user["login"]
        req = app_req(login, "r")
        started = now()
        with lock:
            r = rings.setdefault(mac, new_ring(mac))
            if "reach" in r["pending"]:
                return ok(busy="reach")
            r["pending"]["reach"] = {"since": started, "requested": started, "reqId": req, "confirmed": True}
            r["errors"].pop("reach", None)
        push_ring(mac)

        def run():
            loc = locate(mac, login)
            with lock:
                r2 = rings.setdefault(mac, new_ring(mac))
                r2["pending"].pop("reach", None)
                if loc and loc.get("reachable"):
                    r2["values"]["reach"] = {"ts": now(), "dur": now() - started, "source": "phone",
                                             "by": phone_by(req), "via": "r", "reqId": req,
                                             "data": {"reachable": True, "rssi": loc["rssi"], "gateway": loc["gateway"],
                                                      "ranking": loc["ranking"]}}
                    r2["errors"].pop("reach", None)
                else:
                    r2["errors"]["reach"] = {"ts": now(), "code": "ring_disconnected", "dur": now() - started}
            push_ring(mac)
        threading.Thread(target=run, daemon=True).start()
        return ok(cmd="reach", reqId=req, started=started, wearCheck=WEAR_CHECK_SECONDS)
    else:
        # TV Android : mesure HR (la batterie d'abord, la TV exécute les commandes dans l'ordre)
        cmd = "hr"
        mqttc.publish(f"{PREFIX}/{topic_mac(mac)}/cmd", json.dumps({"cmd": "battery", "reqId": app_req(g.user["login"], "r")}), qos=1)
    res, code = send_cmd(mac, cmd, g.user["login"] + " (état)", "r")
    if code == 409 and res.get("busy"):
        return ok(busy=res["busy"])
    if not res.get("ok"):
        return jsonify(res), code
    return ok(cmd=cmd, reqId=res.get("reqId"), started=now(), wearCheck=WEAR_CHECK_SECONDS)


@app.get("/api/client/ring/<key>/locations")
@auth_required
def api_locations(key):
    """Historique des déplacements (table ring_locations) : arrivée dans une pièce, hors portée, retour."""
    mac, acc = ring_or_404(key)
    if not acc:
        return fail("Bague non affectée à ce compte", 404)
    if not acc["can_view_history"]:
        return fail("Historique non autorisé", 403)
    try:
        hours = min(max(int(request.args.get("hours", "24")), 1), 24 * 90)
    except ValueError:
        hours = 24
    try:
        rows = dbq.location_history(mac, hours)
    except Exception as e:
        return fail(f"Base indisponible : {e}", 503)
    names = zones_cfg.get("names") or {}
    for x in rows:      # nom de pièce de l'admin (« Chambre 12 ») si la base n'en a pas
        x["zone"] = names.get(x["gateway"] or "") or x["zone"]
        x["prevZone"] = names.get(x["prevGateway"] or "") or x["prevZone"]
    return ok(rows=rows, hours=hours)


@app.get("/api/client/ring/<key>/history")
@auth_required
def api_history(key):
    mac, acc = ring_or_404(key)
    if not acc:
        return fail("Bague non affectée à ce compte", 404)
    if not acc["can_view_history"]:
        return fail("Historique non autorisé", 403)
    typ = request.args.get("type", "hr")
    if typ not in visible_measures(acc) or typ not in DB_METRIC:
        return fail("Mesure non autorisée", 403)
    try:
        hours = min(max(int(request.args.get("hours", "24")), 1), 24 * 90)
    except ValueError:
        hours = 24
    try:
        rows = dbq.history(mac, DB_METRIC[typ], 2000)
    except Exception as e:
        return fail(f"Base indisponible : {e}", 503)
    limit = now() - hours * 3600
    out = []
    for x in rows:
        t = int(x["time"].timestamp())
        if t < limit:
            continue
        ex = x["extra"] or {}
        out.append({"ts": t, "value": x["value"], "dbp": ex.get("dbp"), "status": x["status"],
                    "reason": x["reason"], "dur": ex.get("duration_s"), "source": ex.get("origin")})
    return ok(rows=out, type=typ, hours=hours)


@app.get("/api/client/ring/<key>/sleep")
@auth_required
def api_sleep(key):
    """Historique du sommeil (une ligne par nuit) : 7 ou 30 derniers jours."""
    mac, acc = ring_or_404(key)
    if not acc:
        return fail("Bague non affectée à ce compte", 404)
    if not acc["can_view_history"]:
        return fail("Historique non autorisé", 403)
    try:
        days = min(max(int(request.args.get("days", "30")), 1), 400)   # jusqu'à un an (écran graphique)
    except ValueError:
        days = 30
    phases = request.args.get("phases", "1") != "0"
    try:
        return ok(nights=dbq.sleep_nights(mac, days, phases), days=days)
    except Exception as e:
        return fail(f"Base indisponible : {e}", 503)


@app.get("/api/client/ring/<key>/sleep/night")
@auth_required
def api_sleep_night(key):
    """Une nuit en détail (écran « Sommeil graphique ») : phases + mesures enregistrées pendant la nuit."""
    mac, acc = ring_or_404(key)
    if not acc:
        return fail("Bague non affectée à ce compte", 404)
    if not acc["can_view_history"]:
        return fail("Historique non autorisé", 403)
    date = (request.args.get("date") or "")[:10]
    try:
        nights = [n for n in dbq.sleep_nights(mac, 400) if n["date"] == date]
        if not nights:
            return fail("Nuit introuvable", 404)
        n = nights[0]
        return ok(night=n, vitals=dbq.night_vitals(mac, n["start"], n["end"]))
    except Exception as e:
        return fail(f"Base indisponible : {e}", 503)


@app.get("/api/client/alerts")
@auth_required
def api_alerts():
    rows = clientdb.user_alerts(g.user["id"], min(int(request.args.get("limit", "50")), 200))
    return ok(alerts=[{"id": a["id"], "kind": a["kind"], "title": a["title"], "message": a["message"],
                       "ts": int(a["created_at"].timestamp()), "mac": a["mac"].upper(), "label": a["label"]}
                      for a in rows])


# ============================================================================ temps réel (SSE)

subscribers = []   # {"uid", "q", "macs": {mac: acc}}
subs_lock = threading.Lock()


def push_ring(mac):
    with subs_lock:
        subs = list(subscribers)
    for s in subs:
        acc = s["macs"].get(mac)
        if not acc:
            continue
        msg = json.dumps({"type": "ring", "mac": mac, "live": live_state(mac, acc)}, default=str)
        try:
            s["q"].put_nowait(msg)
        except queue.Full:
            pass


def push_user(uid, payload):
    msg = json.dumps(payload, default=str)
    with subs_lock:
        subs = [s for s in subscribers if s["uid"] == uid]
    for s in subs:
        try:
            s["q"].put_nowait(msg)
        except queue.Full:
            pass


@app.get("/api/client/stream")
@auth_required
def api_stream():
    uid = g.user["id"]
    accs = {a["mac"].upper(): a for a in clientdb.user_rings(uid)}
    sub = {"uid": uid, "q": queue.Queue(maxsize=500), "macs": accs}
    with subs_lock:
        subscribers.append(sub)
    hello = json.dumps({"type": "hello", "rings": [ring_payload(a) for a in accs.values()]}, default=str)

    def gen():
        last_reload = time.time()
        try:
            yield "retry: 3000\n\n"
            yield f"data: {hello}\n\n"
            while True:
                try:
                    yield f"data: {sub['q'].get(timeout=15)}\n\n"
                except queue.Empty:
                    yield ": ping\n\n"
                # Droits relus régulièrement : une bague retirée par l'admin disparaît du flux
                if time.time() - last_reload > 60:
                    last_reload = time.time()
                    try:
                        sub["macs"] = {a["mac"].upper(): a for a in clientdb.user_rings(uid)}
                    except Exception:
                        pass
        finally:
            with subs_lock:
                if sub in subscribers:
                    subscribers.remove(sub)

    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ============================================================================ Firebase (FCM)

class Fcm:
    """Envoi des notifications Firebase (API HTTP v1). Désactivé si FCM_SERVICE_ACCOUNT_FILE est absent."""

    def __init__(self, path):
        self.enabled = False
        self.creds = None
        self.project = None
        self.lock = threading.Lock()
        if not path:
            log.info("FCM désactivé (FCM_SERVICE_ACCOUNT_FILE absent du .env)")
            return
        p = Path(path)
        if not p.is_absolute():
            p = HERE / p
        try:
            from google.oauth2 import service_account  # noqa: F401
            import google.auth.transport.requests  # noqa: F401
            import requests  # noqa: F401
            info = json.loads(p.read_text(encoding="utf-8"))
            self.project = info["project_id"]
            self.creds = service_account.Credentials.from_service_account_info(
                info, scopes=["https://www.googleapis.com/auth/firebase.messaging"])
            self.enabled = True
            log.info("FCM activé (projet Firebase %s)", self.project)
        except ImportError:
            log.warning("FCM désactivé : pip install google-auth requests")
        except Exception as e:
            log.warning("FCM désactivé : clé de service illisible (%s)", e)

    def _bearer(self):
        import google.auth.transport.requests as gtr
        with self.lock:
            if not self.creds.valid:
                self.creds.refresh(gtr.Request())
            return self.creds.token

    def send(self, token, title, body, data):
        """True si envoyé ; False si le jeton est invalide (à supprimer) ; None sinon."""
        if not self.enabled:
            return None
        import requests
        msg = {"message": {"token": token, "notification": {"title": title, "body": body},
                           "data": {k: str(v) for k, v in data.items()},
                           "android": {"priority": "high", "notification": {"sound": "default"}}}}
        try:
            r = requests.post(f"https://fcm.googleapis.com/v1/projects/{self.project}/messages:send",
                              headers={"Authorization": f"Bearer {self._bearer()}"}, json=msg, timeout=10)
        except Exception as e:
            log.warning("FCM : envoi impossible (%s)", e)
            return None
        if r.status_code == 200:
            return True
        if r.status_code in (400, 404) and ("UNREGISTERED" in r.text or "INVALID_ARGUMENT" in r.text):
            return False
        log.warning("FCM : réponse %s %s", r.status_code, r.text[:200])
        return None


fcm = Fcm(FCM_FILE)


# ============================================================================ alertes

TEXTS = {
    "removed": {"fr": ("🖐 Bague retirée", "{label} : la bague n'est pas portée."),
                "en": ("🖐 Ring removed", "{label}: the ring is not being worn."),
                "ar": ("🖐 الخاتم منزوع", "{label}: الخاتم غير مرتدى.")},
    "out_of_range": {"fr": ("🔴 Bague hors portée", "{label} : la bague s'est éloignée de la Gateway RHM."),
                     "en": ("🔴 Ring out of range", "{label}: the ring is out of reach of the Gateway RHM."),
                     "ar": ("🔴 الخاتم خارج النطاق", "{label}: ابتعد الخاتم عن بوابة RHM.")},
    "gateway_offline": {"fr": ("⚫ Gateway RHM hors ligne", "{label} : la Gateway RHM est éteinte ou sans internet."),
                        "en": ("⚫ Gateway RHM offline", "{label}: the Gateway RHM is off or has no internet."),
                        "ar": ("⚫ بوابة RHM غير متصلة", "{label}: بوابة RHM مطفأة أو بلا إنترنت.")},
    "unbound": {"fr": ("⚪ Bague dissociée", "{label} : la bague a été dissociée de la Gateway RHM, plus aucune mesure."),
                "en": ("⚪ Ring unpaired", "{label}: the ring was unpaired from the Gateway RHM, no more readings."),
                "ar": ("⚪ الخاتم غير مرتبط", "{label}: تم فصل الخاتم عن بوابة RHM، لا مزيد من القياسات.")},
    "bound": {"fr": ("✅ Bague associée", "{label} : la bague est de nouveau associée à la Gateway RHM."),
              "en": ("✅ Ring paired", "{label}: the ring is paired with the Gateway RHM again."),
              "ar": ("✅ الخاتم مرتبط", "{label}: الخاتم مرتبط ببوابة RHM مجددًا.")},
    "battery_low": {"fr": ("🪫 Batterie faible", "{label} : batterie à {battery} %."),
                    "en": ("🪫 Low battery", "{label}: battery at {battery}%."),
                    "ar": ("🪫 بطارية منخفضة", "{label}: البطارية {battery}٪.")},
    "measure_failed": {"fr": ("ℹ️ Mesure échouée", "{label} : mesure {what} échouée."),
                       "en": ("ℹ️ Measurement failed", "{label}: {what} measurement failed."),
                       "ar": ("ℹ️ فشل القياس", "{label}: فشل قياس {what}.")},
    "restored_range": {"fr": ("✅ Bague reconnectée", "{label} : la bague est de nouveau à portée."),
                       "en": ("✅ Ring reconnected", "{label}: the ring is back in range."),
                       "ar": ("✅ عاد الاتصال بالخاتم", "{label}: الخاتم ضمن النطاق مجددًا.")},
    "restored_gateway": {"fr": ("✅ Gateway RHM en ligne", "{label} : la Gateway RHM répond de nouveau."),
                         "en": ("✅ Gateway RHM online", "{label}: the Gateway RHM is responding again."),
                         "ar": ("✅ بوابة RHM متصلة", "{label}: بوابة RHM تستجيب مجددًا.")},
}


class Alerts:
    """Même logique que les alertes du bot : hors portée / Gateway RHM hors ligne confirmés après
    CLIENT_ALERT_CONFIRM_SECONDS, retirée immédiate, batterie faible une fois.
    Pas d'alerte pour l'état déjà présent quand le service découvre la bague."""

    def __init__(self):
        self.st = {}
        self.q = queue.Queue(maxsize=1000)
        self.lock = threading.Lock()

    def _s(self, mac):
        return self.st.setdefault(mac, {"base": False, "worn": None, "out_since": None, "out_sent": False,
                                        "gw_since": None, "gw_sent": False, "batt_sent": False, "battery": None,
                                        "unbound": False})

    def observe(self, mac, r):
        """Appelé à chaque message de la bague (état déjà mis à jour)."""
        with self.lock:
            s = self._s(mac)
            gw_on = gateway_online(r)
            out = gw_on and r["ring"] in ("disconnected", "connecting")
            batt = r["battery"]
            low = batt is not None and batt < BATTERY_LOW and not r["charging"]
            if not s["base"]:
                if not r["statusTs"]:
                    return
                # Premier statut reçu : état de départ, sans alerte
                s.update(base=True, worn=r["worn"], out_since=now() if out else None, out_sent=out,
                         gw_since=None, gw_sent=False, batt_sent=low, battery=batt,
                         unbound=r["ring"] == "unbound")
                return
            # Dissociée / associée de nouveau à la Gateway RHM
            unb = r["ring"] == "unbound"
            if unb != s["unbound"]:
                s["unbound"] = unb
                self.q.put((mac, "unbound" if unb else "bound", {}))
                if unb:
                    s["out_since"], s["out_sent"] = None, False
            if r["worn"] is False and s["worn"] is not False:
                self.q.put((mac, "removed", {}))
            s["worn"] = r["worn"]
            if gw_on:
                if s["gw_sent"]:
                    self.q.put((mac, "restored_gateway", {}))
                s["gw_since"], s["gw_sent"] = None, False
            if out:
                s["out_since"] = s["out_since"] or now()
            else:
                if s["out_sent"] and r["ring"] == "connected":
                    self.q.put((mac, "restored_range", {}))
                if r["ring"] == "connected" or not gw_on:
                    s["out_since"], s["out_sent"] = None, False
            if low and not s["batt_sent"]:
                s["batt_sent"] = True
                self.q.put((mac, "battery_low", {"battery": batt}))
            elif batt is not None and (batt >= BATTERY_LOW + 5 or r["charging"]):
                s["batt_sent"] = False

    def tick(self):
        """Toutes les 5 s : confirmation des coupures (hors portée, Gateway RHM hors ligne)."""
        t = now()
        with lock:
            snap = {m: json.loads(json.dumps(r, default=str)) for m, r in rings.items()}
        with self.lock:
            for mac, r in snap.items():
                s = self.st.get(mac)
                if not s or not s["base"]:
                    continue
                if not gateway_online(r):
                    s["gw_since"] = s["gw_since"] or t
                    if not s["gw_sent"] and t - s["gw_since"] >= ALERT_CONFIRM:
                        s["gw_sent"] = True
                        self.q.put((mac, "gateway_offline", {}))
                elif s["gw_sent"]:
                    # Retour de la Gateway RHM sans message de la bague (bague dissociée)
                    s["gw_since"], s["gw_sent"] = None, False
                    self.q.put((mac, "restored_gateway", {}))
                if s["out_since"] and not s["out_sent"] and t - s["out_since"] >= ALERT_CONFIRM:
                    s["out_sent"] = True
                    self.q.put((mac, "out_of_range", {}))

    def worker(self):
        while True:
            mac, kind, extra = self.q.get()
            try:
                self._dispatch(mac, kind, extra)
            except Exception:
                log.exception("alerte %s %s", kind, mac)

    def _dispatch(self, mac, kind, extra):
        rid = ring_id(mac)
        if rid is None:
            return
        with lock:
            rr = rings.get(mac) or {}
            db_name = rr.get("name") or ""
            ble = rr.get("bleName") or ""
        name = ble or db_name or mac

        def lbl(u):
            # Nom Bluetooth de la bague (« R10_6401 »), sinon le nom donné par l'admin
            return ble or u.get("label") or db_name or mac

        fr_t, fr_b = TEXTS[kind]["fr"]
        row = clientdb.add_alert(rid, kind, fr_t, fr_b.format(label=name, **extra))
        users = clientdb.recipients(rid)
        log.info("Alerte %s pour %s → %d compte(s)", kind, mac, len(users))
        if not users:
            return
        by_user = {u["user_id"]: u for u in users}
        for u in users:
            t, b = TEXTS[kind].get(u["lang"]) or TEXTS[kind]["fr"]
            push_user(u["user_id"], {"type": "alert", "alert": {
                "id": row["id"], "kind": kind, "title": t, "message": b.format(label=lbl(u), **extra),
                "ts": int(row["created_at"].timestamp()), "mac": mac, "label": lbl(u)}})
        if not fcm.enabled:
            return
        for d in clientdb.device_tokens(list(by_user)):
            u = by_user[d["user_id"]]
            t, b = TEXTS[kind].get(u["lang"]) or TEXTS[kind]["fr"]
            res = fcm.send(d["fcm_token"], t, b.format(label=lbl(u), **extra),
                           {"mac": mac, "kind": kind, "alertId": row["id"]})
            if res is False:
                clientdb.remove_device(d["fcm_token"])


alerts = Alerts()


def watchdog():
    while True:
        time.sleep(5)
        try:
            alerts.tick()
        except Exception:
            log.exception("watchdog")
        # TV sans statut depuis trop longtemps : l'app voit « Gateway RHM hors ligne »
        t = now()
        stale = []
        with lock:
            for mac, r in rings.items():
                if r.get("gatewayType") == "linux":
                    on = linux_online(mac)          # en ligne = une Pi de ses zones répond
                    if on != r["online"]:
                        r["online"] = on
                        stale.append(mac)
                elif r["online"] and r["statusTs"] and t - r["statusTs"] > OFFLINE_AFTER:
                    r["online"] = False
                    stale.append(mac)
                for k, p in list(r["pending"].items()):
                    if t - p["since"] > 150:
                        r["pending"].pop(k, None)
                        stale.append(mac)
                # Course sans gagnante depuis 45 s : l'erreur est affichée
                for sub, last in race.expired(r):
                    handle_result(r, sub, dict(last, roaming="final"))
                    stale.append(mac)
        for mac in set(stale):
            push_ring(mac)


def main():
    dbq.test()
    if not clientdb.tables_ready():
        log.warning("Tables QRingClient absentes : lancez client_migration.sql une fois")
    seed_from_db()
    start_mqtt()
    threading.Thread(target=watchdog, daemon=True).start()
    if REACH_CYCLE_PAUSE > 0:
        threading.Thread(target=reach_cycle, daemon=True).start()
    threading.Thread(target=alerts.worker, daemon=True).start()
    ssl = (SSL_CERT, SSL_KEY) if SSL_CERT and SSL_KEY else None
    log.info("QRingClient API sur %s://0.0.0.0:%d (broker %s:%d, préfixe %s, PostgreSQL %s, FCM %s)",
             "https" if ssl else "http", PORT, MQTT_HOST, MQTT_PORT, PREFIX, dbq.status()["message"],
             "oui" if fcm.enabled else "non")
    app.run(host="0.0.0.0", port=PORT, threaded=True, debug=False, ssl_context=ssl)


if __name__ == "__main__":
    main()
