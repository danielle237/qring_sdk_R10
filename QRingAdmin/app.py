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

import paho.mqtt.client as mqtt  # noqa: E402
from flask import Flask, Response, jsonify, redirect, render_template, request, session, url_for  # noqa: E402

import dbq  # noqa: E402
import telegram_notify as tg  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("qring")

MQTT_HOST = os.getenv("MQTT_HOST", "51.83.40.138")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER", "")
MQTT_PASS = os.getenv("MQTT_PASSWORD", os.getenv("MQTT_PASS", ""))
PREFIX = (os.getenv("MQTT_PREFIX") or os.getenv("MQTT_TOPIC", "eis/colmi/#")).replace("#", "").strip("/")
ADMIN_PASSWORD = os.getenv("QRING_ADMIN_PASSWORD") or os.getenv("ADMIN_PASSWORD") or "admin"
OFFLINE_AFTER = int(os.getenv("QRING_OFFLINE_AFTER", "150"))
PORT = int(os.getenv("QRING_ADMIN_PORT", "5055"))
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
WEBAPP_MAX_AGE = max(300, int(os.getenv("TELEGRAM_WEBAPP_MAX_AGE_SECONDS", "86400")))

MEASURES = ["hr", "spo2", "temp", "bp", "hrv", "stress", "all"]
SYNCS = ["steps", "sleep", "sedentary", "workouts", "history", "battery", "info"]
# métrique PostgreSQL ↔ type de l'app
DB_METRIC = {"hr": "heart_rate", "spo2": "spo2", "temp": "temperature", "bp": "blood_pressure",
             "hrv": "hrv", "stress": "stress", "steps": "steps", "battery": "battery"}
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
    }


def new_gateway(name):
    return {"name": name, "deviceName": "", "ringMac": "", "online": False, "ring": "unknown", "lanIp": None,
            "wanIp": None, "lang": None, "statusTs": 0, "scan": None, "bind": None, "appVersion": ""}


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


def on_connect(client, userdata, flags, reason_code, properties=None):
    if reason_code == 0 or str(reason_code) == "Success":
        client.subscribe(f"{PREFIX}/#", qos=1)
        add_event("ok", f"Connecté au broker {MQTT_HOST}:{MQTT_PORT}")
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
        elif len(rest) == 2 and len(rest[0]) == 12:
            # Format de l'app Android : eis/colmi/<MAC>/<type>
            handle_ring(mac_from_topic(rest[0]), rest[1], payload, f"{PREFIX}/{rest[0].upper()}")
    except Exception as e:
        log.exception("message %s", msg.topic)
        add_event("error", f"Message illisible sur {msg.topic} : {e}")


def handle_gateway(name, sub, p):
    if sub == "cmd":
        return
    with state_lock:
        g = gateways.setdefault(name, new_gateway(name))
        if sub == "status":
            was = g["online"]
            g.update({"online": bool(p.get("online")), "ring": p.get("ring", "unknown"),
                      "ringMac": p.get("ringMac") or "", "deviceName": p.get("deviceName") or g["deviceName"],
                      "lanIp": p.get("lanIp"), "wanIp": p.get("wanIp"), "lang": p.get("lang"),
                      "appVersion": p.get("appVersion", ""), "statusTs": now()})
            if g["online"] and not was:
                add_event("ok", f"Gateway {name} en ligne", gateway=name)
            elif not g["online"] and was:
                add_event("error", f"Gateway {name} hors ligne", gateway=name)
            dbq.enqueue("gateway_status", name=name, deviceName=g["deviceName"], appVersion=g["appVersion"])
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
        elif sub == "lang" and p.get("status") == "ok":
            g["lang"] = p.get("lang")
            add_event("info", f"{name} : langue {p.get('lang')}", gateway=name)
    push_gateway(name)


def handle_ring(mac, sub, p, base_topic):
    if sub == "cmd":
        # Commande publiée par un autre lanceur (bot Telegram…) : la bague devient occupée
        cmd = p.get("cmd")
        if cmd in MEASURES:
            with state_lock:
                r = rings.setdefault(mac, new_ring(mac))
                if cmd not in r["pending"]:
                    src = "telegram" if str(p.get("reqId", "")).startswith("tg-") else "mqtt"
                    r["pending"][cmd] = {"since": now(), "requested": now(), "reqId": p.get("reqId"),
                                         "source": src, "confirmed": False}
                    r["errors"].pop(cmd, None)
                    add_event("info", f"Commande {cmd.upper()} reçue ({'Telegram' if src == 'telegram' else 'MQTT'}) pour {r['name'] or mac}", mac)
            push_ring(mac)
        return
    with state_lock:
        r = rings.setdefault(mac, new_ring(mac))
        gw = p.get("gateway") or r["gateway"]
        r["gateway"] = gw
        if p.get("ringModel"):
            r["model"] = p["ringModel"]

        if sub == "status":
            was_online, was_worn, was_ring = r["online"], r["worn"], r["ring"]
            r.update({
                "online": bool(p.get("online")), "ring": p.get("ring", r["ring"]),
                "name": r.get("dbName") or p.get("ringName") or r["name"], "firmware": p.get("firmware") or r["firmware"],
                "battery": p.get("battery", r["battery"]), "charging": bool(p.get("charging")),
                "worn": p.get("worn", r["worn"]), "measuring": p.get("measuring"),
                "deviceName": p.get("deviceName") or r["deviceName"], "lanIp": p.get("lanIp"),
                "wanIp": p.get("wanIp"), "lang": p.get("lang"), "statusTs": now(),
                "unbound": p.get("ring") == "unbound",
            })
            label = r["name"] or mac
            dbq.enqueue("ring_status", mac=mac, payload=p, gateway=gw, base_topic=base_topic)
            if r["unbound"] and was_ring != "unbound":
                add_event("warn", f"{label} dissociée de {gw}", mac, gw)
            elif r["online"] and not was_online:
                add_event("ok", f"{label} : gateway {gw} en ligne", mac, gw)
            elif not r["online"] and was_online:
                add_event("error", f"{label} : gateway {gw} hors ligne", mac, gw)
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
    push_ring(mac)


def handle_result(r, mac, sub, p, gw, base_topic):
    st = p.get("status")
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
    started = pnd.get("since")
    dur = max(0, now() - started) if started else None
    p = dict(p, _started=started, _dur=dur)
    meta = {"reqId": p.get("reqId") or pnd.get("reqId"), "started": started, "dur": dur}
    if st == "ok":
        data = {k: v for k, v in p.items() if k not in (
            "reqId", "type", "status", "source", "ringMac", "ringModel", "gateway", "ts")}
        data = {k: v for k, v in data.items() if not k.startswith("_")}
        r["values"][sub] = dict(meta, ts=ts, data=data, source=p.get("source"))
        r["errors"].pop(sub, None)
        if sub == "all":
            for k in ("hr", "spo2", "temp", "hrv", "stress"):
                if k in data:
                    r["values"][k] = dict(meta, ts=ts, data={"value": data[k]}, source=p.get("source"))
            if "sbp" in data:
                r["values"]["bp"] = dict(meta, ts=ts, data={"sbp": data["sbp"], "dbp": data.get("dbp")}, source=p.get("source"))
        if sub == "battery":
            r["battery"] = data.get("value", r["battery"])
            r["charging"] = bool(data.get("charging"))
        if sub in MEASURES:
            r["worn"] = True
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

@app.route("/api/state")
@login_required
def api_state():
    s = dbq.status()
    with state_lock:
        return jsonify({"rings": list(rings.values()), "gateways": list(gateways.values()),
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


@app.route("/api/gateway/<name>/cmd", methods=["POST"])
@login_required
def api_gateway_cmd(name):
    body = request.get_json(force=True, silent=True) or {}
    cmd = body.get("cmd")
    if cmd not in ("bind", "unbind", "scan", "lang", "ping"):
        return fail("commande inconnue")
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
                                          "model", "firmware", "statusTs", "unbound", "pending", "errors")}
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
    dbq.start_worker()
    start_mqtt()
    threading.Thread(target=watchdog, daemon=True).start()
    log.info("QRing Admin sur http://0.0.0.0:%d (broker %s:%d, préfixe %s, PostgreSQL %s)",
             PORT, MQTT_HOST, MQTT_PORT, PREFIX, dbq.status()["message"])
    app.run(host="0.0.0.0", port=PORT, threaded=True, debug=False)


if __name__ == "__main__":
    main()
