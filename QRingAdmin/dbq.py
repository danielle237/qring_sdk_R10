"""
QRing Admin — accès PostgreSQL (base smart_ring de DANY).

- Écrit les résultats de l'app Android (gateway TV) dans les tables existantes :
  gateways, rings, ring_current_state, ring_measurements, ring_events
- Gestion Telegram : utilisateurs, affectations ring_telegram_access, appariements QR,
  sessions Web App (mêmes requêtes que db_service.py de DANY, qui n'est pas modifié)

Toutes les écritures MQTT passent par une file + un thread : le thread MQTT n'est jamais bloqué.
"""
import json
import logging
import os
import queue
import threading
import time
from datetime import datetime, timezone

log = logging.getLogger("qring.db")

try:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb
except Exception:  # l'admin démarre même sans psycopg (mode sans base)
    psycopg = None
    dict_row = None
    Jsonb = None


def _env_bool(name, default):
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on", "oui")


DB_ENABLED = _env_bool("DB_ENABLED", "1")
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "smart_ring")
DB_USER = os.getenv("DB_USER", "iti")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_CONNECT_TIMEOUT = int(os.getenv("DB_CONNECT_TIMEOUT", "5"))
PAIRING_DEFAULT_ALERTS = _env_bool("PAIRING_DEFAULT_ALERTS", "0")
WEBAPP_ACTIVE_SECONDS = max(30, int(os.getenv("TELEGRAM_WEBAPP_ACTIVE_SECONDS", "60")))

# Mesures pouvant être autorisées une par une (colonne allowed_measures)
MEASURE_KEYS = ["hr", "spo2", "temp", "bp", "hrv", "stress", "all"]

# Types de l'app Android → métrique PostgreSQL (mêmes noms que la Pi400 quand ils existent)
METRIC = {
    "hr": ("heart_rate", "bpm", "heart_rate"),
    "spo2": ("spo2", "%", "spo2"),
    "temp": ("temperature", "°C", "temperature"),
    "hrv": ("hrv", "ms", "hrv"),
    "stress": ("stress", "score", None),
}

_status_lock = threading.Lock()
_status = {
    "enabled": DB_ENABLED, "connected": False, "database": DB_NAME, "host": DB_HOST,
    "message": "En attente" if DB_ENABLED else "Désactivée (DB_ENABLED=0)",
    "last_error": None, "last_error_time": None,
    "writes_ok": 0, "write_errors": 0, "last_write_time": None, "queue": 0,
    "allowed_measures_column": False,
}
_queue = queue.Queue(maxsize=5000)
_gateway_ids = {}
_ring_ids = {}


def now_utc():
    return datetime.now(timezone.utc)


def status():
    with _status_lock:
        s = dict(_status)
    s["queue"] = _queue.qsize()
    return s


def _set(**kw):
    with _status_lock:
        _status.update(kw)


def connect():
    if not DB_ENABLED:
        raise RuntimeError("DB_ENABLED=0")
    if psycopg is None:
        raise RuntimeError("psycopg non installé (pip install 'psycopg[binary]')")
    conn = psycopg.connect(host=DB_HOST, port=DB_PORT, dbname=DB_NAME, user=DB_USER,
                           password=DB_PASSWORD, connect_timeout=DB_CONNECT_TIMEOUT,
                           row_factory=dict_row)
    conn.autocommit = True
    return conn


def test():
    """Vérifie la connexion et la présence de la colonne allowed_measures."""
    if not DB_ENABLED:
        _set(connected=False, message="Désactivée (DB_ENABLED=0)")
        return False
    try:
        with connect() as c:
            row = c.execute("SELECT current_database() AS db").fetchone()
            col = c.execute(
                """SELECT 1 FROM information_schema.columns
                   WHERE table_name='ring_telegram_access' AND column_name='allowed_measures'"""
            ).fetchone()
        _set(connected=True, message=f"PostgreSQL connecté : {row['db']}", database=row["db"],
             allowed_measures_column=bool(col))
        return True
    except Exception as e:
        _set(connected=False, message=f"PostgreSQL indisponible : {e}", last_error=str(e),
             last_error_time=now_utc().isoformat())
        return False


def has_allowed_measures():
    with _status_lock:
        return bool(_status.get("allowed_measures_column"))


# =============================================================================
# ÉCRITURE DES MESSAGES DE L'APP ANDROID
# =============================================================================

def enqueue(kind, **data):
    """kind : gateway_status | ring_status | result | event"""
    if not DB_ENABLED:
        return
    try:
        _queue.put_nowait((kind, data))
    except queue.Full:
        _set(write_errors=status()["write_errors"] + 1, last_error="File PostgreSQL pleine",
             last_error_time=now_utc().isoformat())


def start_worker():
    if not DB_ENABLED:
        return
    threading.Thread(target=_worker, name="qring-db", daemon=True).start()
    threading.Thread(target=_health, name="qring-db-health", daemon=True).start()


def _health():
    while True:
        test()
        time.sleep(30)


def _worker():
    conn = None
    while True:
        kind, data = _queue.get()
        for attempt in range(3):
            try:
                if conn is None or conn.closed:
                    conn = connect()
                _handle(conn, kind, data)
                s = status()
                _set(connected=True, writes_ok=s["writes_ok"] + 1, last_write_time=now_utc().isoformat())
                break
            except Exception as e:
                log.warning("écriture PostgreSQL (%s) : %s", kind, e)
                s = status()
                _set(write_errors=s["write_errors"] + 1, last_error=f"{kind} : {e}",
                     last_error_time=now_utc().isoformat())
                try:
                    if conn is not None:
                        conn.close()
                except Exception:
                    pass
                conn = None
                if attempt < 2:
                    time.sleep(1 + attempt * 2)
                else:
                    _set(connected=False)


def _ts(value):
    try:
        v = int(value)
        return datetime.fromtimestamp(v, tz=timezone.utc)
    except Exception:
        return now_utc()


def _gateway_id(c, name, device_name=None, version=None):
    if not name:
        return None
    gid = _gateway_ids.get(name)
    row = c.execute(
        """INSERT INTO gateways (name, location, software_version, last_seen)
           VALUES (%s, %s, %s, NOW())
           ON CONFLICT (name) DO UPDATE SET
               location = COALESCE(NULLIF(EXCLUDED.location, ''), gateways.location),
               software_version = COALESCE(EXCLUDED.software_version, gateways.software_version),
               last_seen = NOW(), updated_at = NOW()
           RETURNING id""",
        (name, device_name or None, f"QRing Android {version}" if version else None),
    ).fetchone()
    gid = row["id"]
    _gateway_ids[name] = gid
    return gid


def _ring_id(c, mac, name=None, model=None, firmware=None, base_topic=None):
    rid = _ring_ids.get(mac)
    if rid and not (name or model or firmware):
        c.execute("UPDATE rings SET last_seen = NOW() WHERE id = %s", (rid,))
        return rid
    display = name or (f"COLMI {model}" if model else f"COLMI {mac}")
    row = c.execute(
        """INSERT INTO rings (mac, name, model, fw_version, mqtt_base_topic, last_seen)
           VALUES (%s::macaddr, %s, %s, %s, %s, NOW())
           ON CONFLICT (mac) DO UPDATE SET
               model = COALESCE(EXCLUDED.model, rings.model),
               fw_version = COALESCE(EXCLUDED.fw_version, rings.fw_version),
               last_seen = NOW(), updated_at = NOW()
           RETURNING id""",
        (mac, display, model or None, firmware or None, base_topic),
    ).fetchone()
    _ring_ids[mac] = row["id"]
    return row["id"]


def _current(c, ring_id, gateway_id, fields):
    """UPSERT de ring_current_state (seulement les colonnes fournies)."""
    allowed = {"online", "battery", "charging", "heart_rate", "spo2", "hrv", "fatigue", "health_check",
               "temperature", "steps", "distance_m", "calories_raw", "rssi", "wear_status", "ble_status",
               "last_measurement_at"}
    clean = {k: v for k, v in fields.items() if k in allowed}
    c.execute(
        """INSERT INTO ring_current_state (ring_id, gateway_id, online, updated_at)
           VALUES (%s, %s, %s, NOW())
           ON CONFLICT (ring_id) DO UPDATE SET gateway_id = COALESCE(EXCLUDED.gateway_id, ring_current_state.gateway_id)""",
        (ring_id, gateway_id, bool(clean.get("online", False))),
    )
    if clean:
        sets = ", ".join(f"{k} = %s" for k in clean)
        c.execute(f"UPDATE ring_current_state SET {sets}, updated_at = NOW() WHERE ring_id = %s",
                  list(clean.values()) + [ring_id])


def _measure(c, when, ring_id, gateway_id, metric, value, unit, status_, reason=None, extra=None):
    c.execute(
        """INSERT INTO ring_measurements (time, ring_id, gateway_id, metric, value, unit, status, reason, experimental, extra)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (when, ring_id, gateway_id, metric, value, unit, status_, reason,
         metric in ("hrv", "stress", "fatigue", "health_check"), Jsonb(extra or {})),
    )


def _event(c, when, ring_id, gateway_id, event_type, severity="info", reason=None, details=None):
    c.execute(
        """INSERT INTO ring_events (time, ring_id, gateway_id, event_type, severity, reason, details)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (when, ring_id, gateway_id, event_type, severity, reason, Jsonb(details or {})),
    )


def _num(v):
    try:
        return None if v is None or isinstance(v, bool) else float(v)
    except Exception:
        return None


# Erreurs de l'app → statut PostgreSQL (mêmes valeurs que le reste du système)
FAIL_STATUS = {
    "ring_removed": ("measurement_failed", "ring_removed"),
    "timeout": ("measurement_failed", "timeout"),
    "measure_failed": ("measurement_failed", "measure_failed"),
    "invalid_value": ("measurement_failed", "invalid_value"),
    "ring_disconnected": ("hors_portee", "device_out_of_range"),
}


def _handle(c, kind, d):
    if kind == "gateway_status":
        _gateway_id(c, d["name"], d.get("deviceName"), d.get("appVersion"))
        return

    mac = d["mac"]
    p = d.get("payload") or {}
    gid = _gateway_id(c, d.get("gateway"), p.get("deviceName"), p.get("appVersion")) if d.get("gateway") else None
    rid = _ring_id(c, mac, p.get("ringName") or None, p.get("ringModel") or None,
                   p.get("firmware") or None, d.get("base_topic"))
    when = _ts(p.get("ts"))

    if kind == "ring_status":
        ring_state = p.get("ring")
        fields = {
            "online": bool(p.get("online")) and ring_state == "connected",
            "ble_status": {"connected": "ok", "disconnected": "device_out_of_range",
                           "bluetooth_off": "bluetooth_off", "connecting": "connecting"}.get(ring_state, ring_state)
                          if p.get("online") else "gateway_offline",
        }
        if p.get("battery") is not None:
            fields["battery"] = _num(p.get("battery"))
            fields["charging"] = bool(p.get("charging"))
        if p.get("worn") is True:
            fields["wear_status"] = "worn"
        elif p.get("worn") is False:
            fields["wear_status"] = "removed"
        _current(c, rid, gid, fields)
        return

    if kind == "event":
        _event(c, when, rid, gid, d["event_type"], d.get("severity", "info"), d.get("reason"), d.get("details"))
        return

    if kind != "result":
        return
    sub = d["sub"]
    st = p.get("status")
    extra = {"source": "qring_android", "origin": p.get("source"), "reqId": p.get("reqId"), "gateway": d.get("gateway")}
    if p.get("_dur") is not None:
        extra["duration_s"] = p["_dur"]
        extra["started_at"] = p.get("_started")

    if st == "error":
        err = p.get("error")
        if err not in FAIL_STATUS or sub not in list(METRIC) + ["bp", "all"]:
            return  # busy, cancelled, not_supported… : pas une mesure
        status_, reason = FAIL_STATUS[err]
        metric = METRIC[sub][0] if sub in METRIC else ("blood_pressure" if sub == "bp" else "all")
        _measure(c, when, rid, gid, metric, None, None, status_, reason, extra)
        fields = {"last_measurement_at": when}
        if err == "ring_removed":
            fields["wear_status"] = "removed"
        if err == "ring_disconnected":
            fields.update(online=False, ble_status="device_out_of_range")
        _current(c, rid, gid, fields)
        return

    if st != "ok":
        return

    fields = {"online": True, "ble_status": "ok", "last_measurement_at": when}
    if sub in METRIC:
        metric, unit, col = METRIC[sub]
        v = _num(p.get("value"))
        ex = dict(extra)
        if p.get("rri") is not None:
            ex["rri"] = p.get("rri")
        _measure(c, when, rid, gid, metric, v, unit, "ok", None, ex)
        if col:
            fields[col] = v
        fields["wear_status"] = "worn"
    elif sub == "bp":
        _measure(c, when, rid, gid, "blood_pressure", _num(p.get("sbp")), "mmHg", "ok", None,
                 dict(extra, sbp=p.get("sbp"), dbp=p.get("dbp")))
        fields["wear_status"] = "worn"
    elif sub == "all":
        for key, (metric, unit, col) in METRIC.items():
            src = {"hr": "hr", "spo2": "spo2", "temp": "temp", "hrv": "hrv", "stress": "stress"}[key]
            v = _num(p.get(src))
            if v is not None:
                _measure(c, when, rid, gid, metric, v, unit, "ok", None, extra)
                if col:
                    fields[col] = v
        if p.get("sbp") is not None:
            _measure(c, when, rid, gid, "blood_pressure", _num(p.get("sbp")), "mmHg", "ok", None,
                     dict(extra, sbp=p.get("sbp"), dbp=p.get("dbp")))
        fields["wear_status"] = "worn"
    elif sub == "battery":
        v = _num(p.get("value"))
        _measure(c, when, rid, gid, "battery", v, "%", "ok", None, dict(extra, charging=p.get("charging")))
        fields.update(battery=v, charging=bool(p.get("charging")))
    elif sub == "steps":
        for metric, key, unit in (("steps", "steps", "steps"), ("distance", "distance", "m"), ("calories", "calories", "kcal")):
            v = _num(p.get(key))
            if v is not None:
                _measure(c, when, rid, gid, metric, v, unit, "ok", None, extra)
        fields.update(steps=_num(p.get("steps")), distance_m=_num(p.get("distance")), calories_raw=_num(p.get("calories")))
    else:
        return
    _current(c, rid, gid, fields)


# =============================================================================
# LECTURE : BAGUES CONNUES (pour remplir le tableau au démarrage)
# =============================================================================

def load_rings():
    with connect() as c:
        rows = c.execute(
            """SELECT r.id, r.mac::text AS mac, r.name, r.model, r.fw_version, r.active, r.last_seen,
                      cs.online, cs.battery, cs.charging, cs.wear_status, cs.ble_status,
                      cs.heart_rate, cs.spo2, cs.hrv, cs.temperature, cs.steps, cs.last_measurement_at,
                      g.name AS gateway,
                      (SELECT COUNT(*) FROM ring_telegram_access a WHERE a.ring_id = r.id AND a.active) AS tg_count
               FROM rings r
               LEFT JOIN ring_current_state cs ON cs.ring_id = r.id
               LEFT JOIN gateways g ON g.id = cs.gateway_id
               WHERE r.active = TRUE
               ORDER BY r.last_seen DESC NULLS LAST"""
        ).fetchall()
        latest = c.execute(
            """SELECT ring_id, metric, time, value, extra FROM v_ring_latest_measurements
               WHERE status = 'ok' AND metric IN ('heart_rate','spo2','temperature','hrv','stress','blood_pressure','steps')"""
        ).fetchall()
    by_ring = {}
    for m in latest:
        by_ring.setdefault(m["ring_id"], []).append(m)
    for r in rows:
        r["latest"] = by_ring.get(r["id"], [])
    return rows


def telegram_counts():
    with connect() as c:
        rows = c.execute(
            """SELECT r.mac::text AS mac, COUNT(a.id) FILTER (WHERE a.active) AS n
               FROM rings r LEFT JOIN ring_telegram_access a ON a.ring_id = r.id GROUP BY r.mac"""
        ).fetchall()
    return {row["mac"].upper(): row["n"] for row in rows}


def history(mac, metric, limit=300):
    with connect() as c:
        return c.execute(
            """SELECT m.time, m.metric, m.value, m.samples, m.unit, m.status, m.reason, m.extra, g.name AS gateway
               FROM ring_measurements m
               JOIN rings r ON r.id = m.ring_id
               LEFT JOIN gateways g ON g.id = m.gateway_id
               WHERE r.mac = %s::macaddr AND m.metric = %s
               ORDER BY m.time DESC LIMIT %s""",
            (mac, metric, int(limit)),
        ).fetchall()


# =============================================================================
# TELEGRAM : UTILISATEURS ET AFFECTATIONS
# =============================================================================

def get_ring(c, mac):
    return c.execute("SELECT id, mac::text AS mac, name, model FROM rings WHERE mac = %s::macaddr", (mac,)).fetchone()


def list_users():
    with connect() as c:
        return c.execute(
            """SELECT u.id, u.id_telegram, u.firstname, u.lastname, u.pseudo, u.langue_user,
                      u.date_premiere_connexion, u.date_last_connexion, u.active,
                      COALESCE(json_agg(json_build_object('ring_id', r.id, 'name', r.name, 'mac', r.mac::text,
                               'access_active', a.active))
                               FILTER (WHERE r.id IS NOT NULL), '[]') AS rings,
                      COUNT(a.id) FILTER (WHERE a.active) AS rings_count,
                      (SELECT COUNT(*) FROM telegram_webapp_sessions s
                        WHERE s.telegram_user_id = u.id AND s.closed_at IS NULL
                          AND s.last_seen_at >= NOW() - (%s * INTERVAL '1 second')) AS webapp_active,
                      (SELECT MAX(s.last_seen_at) FROM telegram_webapp_sessions s WHERE s.telegram_user_id = u.id) AS webapp_last
               FROM t_user_app_telegram u
               LEFT JOIN ring_telegram_access a ON a.telegram_user_id = u.id
               LEFT JOIN rings r ON r.id = a.ring_id
               GROUP BY u.id
               ORDER BY u.active DESC, u.date_last_connexion DESC NULLS LAST""",
            (WEBAPP_ACTIVE_SECONDS,),
        ).fetchall()


def set_user_active(user_id, active):
    with connect() as c:
        return c.execute(
            """UPDATE t_user_app_telegram SET active = %s, updated_at = NOW() WHERE id = %s
               RETURNING id, id_telegram, firstname, lastname, pseudo, active""",
            (bool(active), int(user_id)),
        ).fetchone()


def list_access(mac):
    extra = ", rta.allowed_measures" if has_allowed_measures() else ""
    with connect() as c:
        ring = get_ring(c, mac)
        if not ring:
            return None, []
        rows = c.execute(
            f"""SELECT rta.id AS access_id, u.id AS telegram_user_id, u.id_telegram, u.firstname, u.lastname,
                       u.pseudo, u.langue_user, u.active AS user_active,
                       rta.can_view, rta.can_view_history, rta.can_live, rta.can_receive_alerts,
                       rta.can_admin, rta.active, rta.updated_at {extra}
                FROM ring_telegram_access rta
                JOIN t_user_app_telegram u ON u.id = rta.telegram_user_id
                WHERE rta.ring_id = %s
                ORDER BY u.firstname NULLS LAST, u.lastname NULLS LAST, u.id_telegram""",
            (ring["id"],),
        ).fetchall()
    return ring, rows


def upsert_access(mac, data):
    """Affecte / modifie. Retourne (access_id, was_active_before)."""
    uid = int(str(data.get("telegram_user_id", "")).strip())

    def b(name, default):
        v = data.get(name, default)
        return v if isinstance(v, bool) else str(v).strip().lower() in ("1", "true", "yes", "on", "oui")

    measures = data.get("allowed_measures")
    if measures is not None:
        measures = [m for m in measures if m in MEASURE_KEYS] or None  # [] ou tout coché → général

    with connect() as c:
        with c.transaction():
            ring = get_ring(c, mac)
            if not ring:
                raise LookupError("Bague inconnue dans PostgreSQL")
            user = c.execute("SELECT id, active FROM t_user_app_telegram WHERE id = %s", (uid,)).fetchone()
            if not user:
                raise LookupError("Utilisateur Telegram inconnu : il doit d'abord faire /start dans le bot")
            if not user["active"]:
                raise ValueError("Utilisateur Telegram désactivé")
            before = c.execute(
                "SELECT active FROM ring_telegram_access WHERE ring_id = %s AND telegram_user_id = %s",
                (ring["id"], uid),
            ).fetchone()
            active = b("active", True)
            cols = "ring_id, telegram_user_id, can_view, can_view_history, can_live, can_receive_alerts, can_admin, active"
            vals = [ring["id"], uid, b("can_view", True), b("can_view_history", True), b("can_live", True),
                    b("can_receive_alerts", False), b("can_admin", False), active]
            upd = """can_view = EXCLUDED.can_view, can_view_history = EXCLUDED.can_view_history,
                     can_live = EXCLUDED.can_live, can_receive_alerts = EXCLUDED.can_receive_alerts,
                     can_admin = EXCLUDED.can_admin, active = EXCLUDED.active, updated_at = NOW()"""
            if has_allowed_measures():
                cols += ", allowed_measures"
                vals.append(measures)
                upd += ", allowed_measures = EXCLUDED.allowed_measures"
            ph = ", ".join(["%s"] * len(vals))
            row = c.execute(
                f"""INSERT INTO ring_telegram_access ({cols}) VALUES ({ph})
                    ON CONFLICT (ring_id, telegram_user_id) DO UPDATE SET {upd}
                    RETURNING id""",
                vals,
            ).fetchone()
    return row["id"], bool(before and before["active"]), active


def delete_access(mac, access_id):
    with connect() as c:
        ring = get_ring(c, mac)
        if not ring:
            raise LookupError("Bague inconnue")
        row = c.execute(
            """DELETE FROM ring_telegram_access WHERE id = %s AND ring_id = %s
               RETURNING telegram_user_id""",
            (int(access_id), ring["id"]),
        ).fetchone()
        return bool(row)


def get_user(user_id):
    with connect() as c:
        return c.execute(
            "SELECT id, id_telegram, firstname, lastname, pseudo, langue_user, active FROM t_user_app_telegram WHERE id = %s",
            (int(user_id),),
        ).fetchone()


# =============================================================================
# APPARIEMENTS QR (mêmes règles que db_service.py)
# =============================================================================

def list_pairing(status_=None, limit=300):
    params, where = [], ""
    if status_ and status_ != "all":
        if status_ not in ("pending", "approved", "rejected", "cancelled"):
            raise ValueError("Statut invalide")
        where, params = "WHERE pr.status = %s", [status_]
    params.append(int(limit))
    with connect() as c:
        return c.execute(
            f"""SELECT pr.id AS request_id, pr.status, pr.requested_at, pr.decided_at,
                       pr.decided_by_telegram_id, pr.decided_by_source, pr.decided_by_label,
                       r.id AS ring_id, r.name AS ring_name, r.mac::text AS mac, r.model,
                       u.id AS telegram_user_id, u.id_telegram, u.firstname, u.lastname, u.pseudo,
                       u.langue_user, u.active AS user_active
                FROM ring_pairing_requests pr
                JOIN rings r ON r.id = pr.ring_id
                JOIN t_user_app_telegram u ON u.id = pr.telegram_user_id
                {where}
                ORDER BY CASE WHEN pr.status = 'pending' THEN 0 ELSE 1 END, pr.requested_at DESC
                LIMIT %s""",
            params,
        ).fetchall()


def pairing_counts():
    with connect() as c:
        rows = c.execute("SELECT status, COUNT(*) AS n FROM ring_pairing_requests GROUP BY status").fetchall()
    return {r["status"]: r["n"] for r in rows}


def _decide_pairing(request_id, approve, label):
    with connect() as c:
        with c.transaction():
            row = c.execute(
                """SELECT pr.id AS request_id, pr.status, pr.ring_id, pr.telegram_user_id,
                          r.name AS ring_name, r.mac::text AS mac, r.model,
                          u.id_telegram, u.firstname, u.lastname, u.pseudo, u.active AS user_active
                   FROM ring_pairing_requests pr
                   JOIN rings r ON r.id = pr.ring_id
                   JOIN t_user_app_telegram u ON u.id = pr.telegram_user_id
                   WHERE pr.id = %s FOR UPDATE""",
                (int(request_id),),
            ).fetchone()
            if not row:
                return None
            if row["status"] != "pending":
                row["result"] = "already_decided"
                return row
            if approve:
                if not row["user_active"]:
                    raise ValueError("Utilisateur Telegram désactivé")
                c.execute(
                    """INSERT INTO ring_telegram_access
                         (ring_id, telegram_user_id, can_view, can_view_history, can_live, can_receive_alerts, can_admin, active)
                       VALUES (%s, %s, TRUE, TRUE, TRUE, %s, FALSE, TRUE)
                       ON CONFLICT (ring_id, telegram_user_id) DO UPDATE SET
                         can_view = TRUE, can_view_history = TRUE, can_live = TRUE,
                         can_receive_alerts = EXCLUDED.can_receive_alerts, can_admin = FALSE,
                         active = TRUE, updated_at = NOW()""",
                    (row["ring_id"], row["telegram_user_id"], PAIRING_DEFAULT_ALERTS),
                )
            new_status = "approved" if approve else "rejected"
            c.execute(
                """UPDATE ring_pairing_requests SET status = %s, decided_at = NOW(),
                          decided_by_telegram_id = NULL, decided_by_source = 'flask', decided_by_label = %s
                   WHERE id = %s""",
                (new_status, str(label)[:128], int(request_id)),
            )
            row["result"] = row["status"] = new_status
            return row


def approve_pairing(request_id, label="QRing Admin"):
    return _decide_pairing(request_id, True, label)


def reject_pairing(request_id, label="QRing Admin"):
    return _decide_pairing(request_id, False, label)


# =============================================================================
# SESSIONS WEB APP
# =============================================================================

def list_webapp_sessions(limit=300):
    with connect() as c:
        return c.execute(
            """SELECT s.id AS session_id, s.opened_at, s.last_seen_at, s.closed_at,
                      (s.closed_at IS NULL AND s.last_seen_at >= NOW() - (%s * INTERVAL '1 second')) AS is_active,
                      EXTRACT(EPOCH FROM (COALESCE(s.closed_at, s.last_seen_at) - s.opened_at))::int AS duration_s,
                      u.id AS telegram_user_id, u.id_telegram, u.firstname, u.lastname, u.pseudo,
                      r.id AS ring_id, r.name AS ring_name, r.mac::text AS mac, r.model
               FROM telegram_webapp_sessions s
               JOIN t_user_app_telegram u ON u.id = s.telegram_user_id
               JOIN rings r ON r.id = s.ring_id
               ORDER BY s.opened_at DESC LIMIT %s""",
            (WEBAPP_ACTIVE_SECONDS, int(limit)),
        ).fetchall()


def webapp_stats():
    with connect() as c:
        return c.execute(
            """SELECT COUNT(*) AS total_sessions,
                      COUNT(*) FILTER (WHERE closed_at IS NULL AND last_seen_at >= NOW() - (%s * INTERVAL '1 second')) AS active_now,
                      COUNT(DISTINCT telegram_user_id) AS unique_users,
                      COUNT(DISTINCT ring_id) AS unique_rings,
                      COUNT(*) FILTER (WHERE opened_at >= date_trunc('day', NOW())) AS today
               FROM telegram_webapp_sessions""",
            (WEBAPP_ACTIVE_SECONDS,),
        ).fetchone() or {}


# =============================================================================
# WEB APP TELEGRAM (Mini App) : accès, sessions, dernières valeurs
# =============================================================================

def webapp_access(id_telegram, mac):
    """Droits d'un utilisateur Telegram actif sur une bague (None si non affecté ou sans « voir »)."""
    extra = ", rta.allowed_measures" if has_allowed_measures() else ", NULL::text[] AS allowed_measures"
    with connect() as c:
        return c.execute(
            f"""SELECT u.id AS telegram_user_id, u.id_telegram, u.firstname, u.lastname, u.pseudo, u.langue_user,
                       r.id AS ring_id, r.name AS ring_name, r.mac::text AS mac, r.model,
                       rta.can_view, rta.can_view_history, rta.can_live, rta.can_receive_alerts, rta.can_admin {extra}
                FROM t_user_app_telegram u
                JOIN ring_telegram_access rta ON rta.telegram_user_id = u.id
                JOIN rings r ON r.id = rta.ring_id
                WHERE u.id_telegram = %s AND r.mac = %s::macaddr
                  AND u.active AND rta.active AND rta.can_view AND r.active""",
            (int(id_telegram), mac),
        ).fetchone()


def webapp_open_session(telegram_user_id, ring_id, auth_date=None, query_id=None):
    import secrets
    token = secrets.token_urlsafe(36)
    with connect() as c:
        row = c.execute(
            """INSERT INTO telegram_webapp_sessions
                   (session_token, telegram_user_id, ring_id, telegram_auth_date, telegram_query_id, active)
               VALUES (%s, %s, %s, %s, %s, TRUE) RETURNING id""",
            (token, int(telegram_user_id), int(ring_id),
             datetime.fromtimestamp(auth_date, timezone.utc) if auth_date else None, query_id),
        ).fetchone()
        c.execute("INSERT INTO telegram_webapp_events (session_id, event_type) VALUES (%s, 'OPEN')", (row["id"],))
    return token


def webapp_session_access(token, touch=True):
    """Session ouverte + droits relus en base à chaque appel (un retrait d'affectation coupe l'accès)."""
    if not token:
        return None
    extra = ", rta.allowed_measures" if has_allowed_measures() else ", NULL::text[] AS allowed_measures"
    with connect() as c:
        if touch:
            c.execute(
                "UPDATE telegram_webapp_sessions SET last_seen_at = NOW(), active = TRUE "
                "WHERE session_token = %s AND closed_at IS NULL", (str(token),))
        return c.execute(
            f"""SELECT s.id AS session_id, u.id AS telegram_user_id, u.id_telegram, u.firstname,
                       r.id AS ring_id, r.name AS ring_name, r.mac::text AS mac, r.model,
                       rta.can_view, rta.can_view_history, rta.can_live {extra}
                FROM telegram_webapp_sessions s
                JOIN t_user_app_telegram u ON u.id = s.telegram_user_id
                JOIN rings r ON r.id = s.ring_id
                JOIN ring_telegram_access rta ON rta.ring_id = r.id AND rta.telegram_user_id = u.id
                WHERE s.session_token = %s AND s.closed_at IS NULL
                  AND u.active AND rta.active AND rta.can_view AND r.active""",
            (str(token),),
        ).fetchone()


def webapp_close_session(token):
    with connect() as c:
        row = c.execute(
            """UPDATE telegram_webapp_sessions SET active = FALSE, closed_at = COALESCE(closed_at, NOW()),
                      last_seen_at = NOW()
               WHERE session_token = %s AND closed_at IS NULL RETURNING id""",
            (str(token),),
        ).fetchone()
        if row:
            c.execute("INSERT INTO telegram_webapp_events (session_id, event_type) VALUES (%s, 'CLOSE')", (row["id"],))
    return bool(row)


LATEST_METRICS = {"heart_rate": "hr", "spo2": "spo2", "hrv": "hrv", "temperature": "temp"}


def latest_values(ring_id):
    """Dernière valeur réussie par mesure, en base."""
    with connect() as c:
        rows = c.execute(
            """SELECT k.metric, m.time, m.value, m.extra
               FROM unnest(%s::text[]) AS k(metric)
               CROSS JOIN LATERAL (
                   SELECT time, value, extra FROM ring_measurements
                   WHERE ring_id = %s AND metric = k.metric AND status = 'ok' AND value IS NOT NULL
                   ORDER BY time DESC LIMIT 1) m""",
            (list(LATEST_METRICS), int(ring_id)),
        ).fetchall()
    return {LATEST_METRICS[r["metric"]]: {"ts": int(r["time"].timestamp()), "data": {"value": r["value"]},
                                          "dur": (r["extra"] or {}).get("duration_s")} for r in rows}
