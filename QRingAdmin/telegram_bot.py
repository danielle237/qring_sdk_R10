import os
import json
import time
import asyncio
import logging
import threading
import re
import uuid
import html as html_lib
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

from dotenv import load_dotenv

# ============================================================
# DANY TELEGRAM BOT V2 - LIVE / HISTORY / QR PAIRING
# Le bot lit DB + MQTT depuis le MEME .env que Flask.
# Place ce fichier dans le même dossier que app.py/.env.
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
# Même .env que QRing Admin : DANY_ENV_FILE, sinon QRING_ENV_FILE, sinon ./.env
ENV_FILE = Path(os.getenv("DANY_ENV_FILE") or os.getenv("QRING_ENV_FILE") or (BASE_DIR / ".env"))
load_dotenv(ENV_FILE)

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


import psycopg
from psycopg.rows import dict_row
import paho.mqtt.client as mqtt

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.constants import ChatType
from telegram.error import BadRequest, Forbidden, RetryAfter
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

# ---------------- Configuration .env ----------------

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_PRIVATE_ONLY = os.getenv("TELEGRAM_PRIVATE_ONLY", "1").strip().strip(",;").strip().lower() not in (
    "0", "false", "no", "off"
)
LIVE_REFRESH_SECONDS = max(
    1.0, env_float("TELEGRAM_LIVE_REFRESH_SECONDS", "2")
)

RING_OVERVIEW_REFRESH_SECONDS = max(
    1.0,
    env_float("TELEGRAM_RING_OVERVIEW_REFRESH_SECONDS", "2"),
)

LIVE_SESSION_MINUTES = max(
    1, env_int("TELEGRAM_LIVE_SESSION_MINUTES", "30")
)

LIVE_WARNING_MINUTES = max(
    1, env_int("TELEGRAM_LIVE_WARNING_MINUTES", "5")
)

# Si plusieurs mesures physiologiques échouent avec
# reason=measurement_failed dans la même fenêtre, la bague est considérée
# ONLINE mais NON PORTÉE.
WEAR_FAILURE_THRESHOLD = max(
    2, env_int("TELEGRAM_WEAR_FAILURE_THRESHOLD", "2")
)

WEAR_FAILURE_WINDOW_SECONDS = max(
    30, env_int("TELEGRAM_WEAR_FAILURE_WINDOW_SECONDS", "180")
)

PHYSIO_METRICS = (
    "heart_rate",
    "spo2",
    "fatigue",
    "health_check",
)

def _parse_int_set(raw):
    out = set()
    for part in str(raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.add(int(part))
        except ValueError:
            pass
    return out


# Administrateurs globaux du bot, séparés par des virgules.
# Exemple : TELEGRAM_ADMIN_IDS=123456789,987654321
TELEGRAM_ADMIN_IDS = _parse_int_set(
    os.getenv("TELEGRAM_ADMIN_IDS", "")
)

# Permissions accordées lorsqu'un administrateur accepte une demande QR.
PAIRING_DEFAULT_ALERTS = os.getenv(
    "PAIRING_DEFAULT_ALERTS", "0"
).strip().strip(",;").strip().lower() in ("1", "true", "yes", "on")

# URL HTTPS publique du Flask DANY.
# Exemple : https://dany.embedded-systems.biz
TELEGRAM_WEBAPP_BASE_URL = os.getenv(
    "TELEGRAM_WEBAPP_BASE_URL",
    "",
).strip().rstrip("/")

DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = env_int("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "smart_ring")
DB_USER = os.getenv("DB_USER", "")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_CONNECT_TIMEOUT = env_int("DB_CONNECT_TIMEOUT", "5")

MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
MQTT_PORT = env_int("MQTT_PORT", "1883")
MQTT_USER = os.getenv("MQTT_USER", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "eis/colmi/#")

logging.basicConfig(
    level=os.getenv("TELEGRAM_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("dany.telegram")

# ---------------- Etat process ----------------

telegram_app = None
telegram_loop = None

# ring_id -> état courant construit avec PostgreSQL + MQTT
live_state = {}
live_state_lock = threading.RLock()

# (chat_id, ring_id) -> session live
live_sessions = {}
live_sessions_lock = threading.RLock()

# (chat_id, ring_id) -> écran "Ring" avant d'entrer en LIVE.
# Cet écran est mis à jour automatiquement par les messages MQTT.
ring_overview_sessions = {}
ring_overview_sessions_lock = threading.RLock()

# Messages Telegram "HORS PORTÉE" envoyés par le bot.
# Clé : (ring_id, chat_id)
# Valeur : message_id Telegram
#
# Quand la bague redevient ONLINE, ces messages sont supprimés du chat
# afin de ne pas laisser un warning obsolète sous l'écran courant.
outside_alert_messages = {}
outside_alert_messages_lock = threading.RLock()

# Liste des rings / mqtt_base_topic
rings_cache = []
rings_cache_lock = threading.RLock()
rings_cache_at = 0.0


# ============================================================
# PostgreSQL
# ============================================================

def get_connection():
    """Connexion entièrement issue du .env."""
    return psycopg.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        connect_timeout=DB_CONNECT_TIMEOUT,
        row_factory=dict_row,
        autocommit=True,
    )


def db_healthcheck():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT current_database() AS db, current_user AS usr")
            return cur.fetchone()


def register_user_from_start(tg_user):
    """Crée/actualise l'utilisateur via la procédure PostgreSQL add_user_2()."""
    now = datetime.now(timezone.utc)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CALL add_user_2(
                    %s, %s, %s, %s, %s, %s, %s, NULL
                )
                """,
                (
                    int(tg_user.id),
                    tg_user.first_name,
                    tg_user.last_name,
                    now,
                    now,
                    tg_user.username,
                    tg_user.language_code,
                ),
            )
            try:
                return cur.fetchone()
            except Exception:
                return None


def get_accessible_rings(telegram_id):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    u.id AS telegram_user_id,
                    r.id AS ring_id,
                    r.name AS ring_name,
                    r.mac::text AS mac,
                    r.model,
                    r.mqtt_base_topic,
                    a.can_view,
                    a.can_view_history,
                    a.can_live,
                    a.can_receive_alerts,
                    a.can_admin,
                    """ + access_measures_sql() + """
                FROM t_user_app_telegram u
                JOIN ring_telegram_access a
                    ON a.telegram_user_id = u.id
                JOIN rings r
                    ON r.id = a.ring_id
                WHERE u.id_telegram = %s
                  AND u.active = TRUE
                  AND a.active = TRUE
                  AND a.can_view = TRUE
                  AND r.active = TRUE
                ORDER BY r.name, r.id
                """,
                (int(telegram_id),),
            )
            return list(cur.fetchall())


def get_ring_access(telegram_id, ring_id):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    u.id AS telegram_user_id,
                    r.id AS ring_id,
                    r.name AS ring_name,
                    r.mac::text AS mac,
                    r.model,
                    r.mqtt_base_topic,
                    a.can_view,
                    a.can_view_history,
                    a.can_live,
                    a.can_receive_alerts,
                    a.can_admin,
                    """ + access_measures_sql() + """
                FROM t_user_app_telegram u
                JOIN ring_telegram_access a
                    ON a.telegram_user_id = u.id
                JOIN rings r
                    ON r.id = a.ring_id
                WHERE u.id_telegram = %s
                  AND r.id = %s
                  AND u.active = TRUE
                  AND a.active = TRUE
                  AND r.active = TRUE
                """,
                (int(telegram_id), int(ring_id)),
            )
            return cur.fetchone()


def get_current_state(ring_id):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    r.id AS ring_id,
                    r.name AS ring_name,
                    r.mac::text AS mac,
                    r.model,
                    r.mqtt_base_topic,
                    s.online,
                    s.battery,
                    s.charging,
                    s.heart_rate,
                    s.spo2,
                    s.hrv,
                    s.fatigue,
                    s.health_check,
                    s.temperature,
                    s.steps,
                    s.distance_m,
                    s.calories_raw,
                    s.rssi,
                    s.wear_status,
                    s.ble_status,
                    s.last_measurement_at,
                    s.updated_at
                FROM rings r
                LEFT JOIN ring_current_state s
                    ON s.ring_id = r.id
                WHERE r.id = %s
                """,
                (int(ring_id),),
            )
            return cur.fetchone()



def get_latest_battery_detail(ring_id):
    """
    Dernière mesure batterie historisée.
    Permet d'afficher le vrai timestamp de la batterie dans Telegram,
    y compris après un redémarrage du bot.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    value,
                    unit,
                    status,
                    reason,
                    time,
                    extra
                FROM ring_measurements
                WHERE ring_id = %s
                  AND metric = 'battery'
                ORDER BY time DESC
                LIMIT 1
                """,
                (int(ring_id),),
            )

            row = cur.fetchone()
            return dict(row) if row else None


def get_latest_sensor_details(ring_id):
    """Dernier résultat complet par capteur, avec samples conservés en DB."""
    metrics = ("heart_rate", "spo2", "hrv", "fatigue", "health_check", "temperature")
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (metric)
                    metric, value, samples, unit, status, reason, time
                FROM ring_measurements
                WHERE ring_id = %s
                  AND metric = ANY(%s)
                ORDER BY metric, time DESC
                """,
                (int(ring_id), list(metrics)),
            )
            return [dict(r) for r in cur.fetchall()]




def seed_live_state_from_db(ring_id):
    """
    Amorce / resynchronise le LIVE depuis PostgreSQL.

    Ordre d'interprétation :
      1) device_not_found / device_out_of_range -> HORS PORTEE
      2) charging=True -> ONLINE NON PORTE
      3) >= N measurement_failed récents -> ONLINE NON PORTE
      4) au moins une mesure physiologique OK récente -> ONLINE PORTE
    """
    current = get_current_state(ring_id) or {}
    details = get_latest_sensor_details(ring_id)
    battery_detail = get_latest_battery_detail(ring_id)

    now_dt = datetime.now(timezone.utc)

    with live_state_lock:
        state = live_state.setdefault(
            int(ring_id),
            {},
        )

        for key, value in dict(current).items():
            if value is not None:
                state[key] = value

        # Timestamp exact de la dernière batterie, lu dans ring_measurements.
        if battery_detail:
            state["battery_timestamp"] = battery_detail.get("time")

            if battery_detail.get("value") is not None:
                state["battery"] = battery_detail.get("value")

            extra = battery_detail.get("extra")
            if isinstance(extra, dict) and extra.get("charging") is not None:
                state["charging"] = bool(extra.get("charging"))

        recent_failures = []
        recent_successes = []

        for row in details:
            metric = row["metric"]
            samples = row.get("samples")
            row_time = row.get("time")

            if samples:
                state[f"{metric}_samples"] = list(samples)

            state[f"{metric}_unit"] = row.get("unit")
            state[f"{metric}_status"] = row.get("status") or "ok"
            state[f"{metric}_reason"] = row.get("reason")
            state[f"{metric}_timestamp"] = row_time

            if metric in PHYSIO_METRICS and row_time:
                try:
                    if row_time.tzinfo is None:
                        row_time = row_time.replace(tzinfo=timezone.utc)

                    age = (
                        now_dt
                        - row_time.astimezone(timezone.utc)
                    ).total_seconds()

                    if age <= WEAR_FAILURE_WINDOW_SECONDS:
                        status = str(
                            row.get("status") or ""
                        ).strip().lower()

                        reason = str(
                            row.get("reason") or ""
                        ).strip().lower()

                        if reason == "measurement_failed":
                            recent_failures.append(metric)

                        elif status == "ok":
                            recent_successes.append(metric)

                except Exception:
                    pass

        ble_status = str(
            state.get("ble_status") or ""
        ).strip().lower()

        outside = (
            state.get("online") is False
            or ble_status in (
                "device_not_found",
                "device_out_of_range",
                "outside",
                "hors_portee",
            )
        )

        state["outside"] = outside

        if outside:
            reason = (
                ble_status
                or "device_out_of_range"
            )

            ts = (
                state.get("last_measurement_at")
                or state.get("updated_at")
            )

            for metric in PHYSIO_METRICS:
                state[f"{metric}_status"] = "hors_portee"
                state[f"{metric}_reason"] = reason
                state[f"{metric}_timestamp"] = ts
                state[f"{metric}_samples"] = None

            return dict(state)

        # ONLINE : inférence du port.
        if state.get("charging") is True:
            state["wear_inferred"] = "not_worn"
            state["wear_inferred_reason"] = "charging"

        elif len(set(recent_failures)) >= WEAR_FAILURE_THRESHOLD:
            state["wear_inferred"] = "not_worn"
            state["wear_inferred_reason"] = (
                "measurement_failed:"
                + ",".join(sorted(set(recent_failures)))
            )

        elif recent_successes:
            state["wear_inferred"] = "worn"
            state["wear_inferred_reason"] = (
                "measurement_ok:"
                + ",".join(sorted(set(recent_successes)))
            )

        return dict(state)

def get_history_summary(ring_id, hours):
    hours = max(1, min(int(hours), 24 * 365))
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    metric,
                    COUNT(*) FILTER (
                        WHERE status='ok' AND value IS NOT NULL
                    ) AS samples_count,
                    AVG(value) FILTER (
                        WHERE status='ok' AND value IS NOT NULL
                    ) AS avg_value,
                    MIN(value) FILTER (
                        WHERE status='ok' AND value IS NOT NULL
                    ) AS min_value,
                    MAX(value) FILTER (
                        WHERE status='ok' AND value IS NOT NULL
                    ) AS max_value,
                    (
                        ARRAY_AGG(value ORDER BY time DESC)
                        FILTER (WHERE status='ok' AND value IS NOT NULL)
                    )[1] AS last_value,
                    MAX(time) AS last_time,
                    COUNT(*) FILTER (
                        WHERE status <> 'ok'
                    ) AS error_count
                FROM ring_measurements
                WHERE ring_id = %s
                  AND time >= NOW() - (%s || ' hours')::interval
                GROUP BY metric
                ORDER BY metric
                """,
                (int(ring_id), hours),
            )
            return list(cur.fetchall())



def get_metric_history(ring_id, metric, hours, limit=100):
    allowed = {
        "heart_rate",
        "spo2",
        "fatigue",
        "health_check",
    }

    if metric not in allowed:
        raise ValueError("Métrique historique non autorisée")

    hours = max(1, min(int(hours), 24 * 365))
    limit = max(1, min(int(limit), 200))

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    time,
                    metric,
                    value,
                    samples,
                    unit,
                    status,
                    reason
                FROM ring_measurements
                WHERE ring_id = %s
                  AND metric = %s
                  AND time >= NOW() - (%s || ' hours')::interval
                ORDER BY time DESC
                LIMIT %s
                """,
                (
                    int(ring_id),
                    metric,
                    hours,
                    limit,
                ),
            )
            return [dict(r) for r in cur.fetchall()]


def get_alert_chat_ids(ring_id):
    """
    Destinataires d'une alerte hors portée :
    - TELEGRAM_ADMIN_IDS
    - utilisateurs affectés avec can_receive_alerts=TRUE
    """
    result = set(TELEGRAM_ADMIN_IDS)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT u.id_telegram
                FROM ring_telegram_access a
                JOIN t_user_app_telegram u
                  ON u.id = a.telegram_user_id
                WHERE a.ring_id = %s
                  AND a.active = TRUE
                  AND a.can_receive_alerts = TRUE
                  AND u.active = TRUE
                  AND u.id_telegram IS NOT NULL
                """,
                (int(ring_id),),
            )

            for row in cur.fetchall():
                try:
                    result.add(int(row["id_telegram"]))
                except Exception:
                    pass

    return sorted(result)


def get_pairing_request(request_id):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    pr.id AS request_id,
                    pr.status,
                    pr.requested_at,
                    pr.ring_id,
                    pr.telegram_user_id,
                    u.id_telegram,
                    u.firstname,
                    u.lastname,
                    u.pseudo,
                    r.name AS ring_name,
                    r.mac::text AS mac,
                    r.model
                FROM ring_pairing_requests pr
                JOIN t_user_app_telegram u
                  ON u.id = pr.telegram_user_id
                JOIN rings r
                  ON r.id = pr.ring_id
                WHERE pr.id = %s
                """,
                (int(request_id),),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def create_pairing_request(telegram_id, token):
    """
    Le QR ne donne PAS automatiquement accès.
    Il crée une demande PENDING que l'admin accepte ou refuse.
    """
    token = str(token or "").strip()

    if not token:
        return {"status": "invalid"}

    with get_connection() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        u.id AS telegram_user_id,
                        pt.id AS pairing_token_id,
                        r.id AS ring_id,
                        r.name AS ring_name,
                        r.mac::text AS mac,
                        r.model
                    FROM t_user_app_telegram u
                    JOIN ring_pairing_tokens pt
                      ON pt.token = %s
                    JOIN rings r
                      ON r.id = pt.ring_id
                    WHERE u.id_telegram = %s
                      AND u.active = TRUE
                      AND pt.active = TRUE
                      AND (
                          pt.expires_at IS NULL
                          OR pt.expires_at > NOW()
                      )
                      AND r.active = TRUE
                    LIMIT 1
                    """,
                    (
                        token,
                        int(telegram_id),
                    ),
                )

                row = cur.fetchone()

                if not row:
                    return {"status": "invalid"}

                row = dict(row)

                cur.execute(
                    """
                    SELECT id
                    FROM ring_telegram_access
                    WHERE ring_id = %s
                      AND telegram_user_id = %s
                      AND active = TRUE
                    LIMIT 1
                    """,
                    (
                        row["ring_id"],
                        row["telegram_user_id"],
                    ),
                )

                if cur.fetchone():
                    row["status"] = "already_assigned"
                    return row

                cur.execute(
                    """
                    SELECT id
                    FROM ring_pairing_requests
                    WHERE ring_id = %s
                      AND telegram_user_id = %s
                      AND status = 'pending'
                    ORDER BY requested_at DESC
                    LIMIT 1
                    """,
                    (
                        row["ring_id"],
                        row["telegram_user_id"],
                    ),
                )

                pending = cur.fetchone()

                if pending:
                    row["request_id"] = pending["id"]
                    row["status"] = "already_pending"
                    return row

                cur.execute(
                    """
                    INSERT INTO ring_pairing_requests (
                        ring_id,
                        telegram_user_id,
                        pairing_token_id,
                        status,
                        requested_at
                    )
                    VALUES (%s, %s, %s, 'pending', NOW())
                    RETURNING id
                    """,
                    (
                        row["ring_id"],
                        row["telegram_user_id"],
                        row["pairing_token_id"],
                    ),
                )

                created = cur.fetchone()
                row["request_id"] = created["id"]
                row["status"] = "pending"
                return row


def approve_pairing_request(request_id, admin_telegram_id):
    """
    Accepte une demande QR et crée/réactive ring_telegram_access.
    """
    with get_connection() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        pr.id AS request_id,
                        pr.status,
                        pr.ring_id,
                        pr.telegram_user_id,
                        u.id_telegram,
                        u.firstname,
                        u.lastname,
                        u.pseudo,
                        r.name AS ring_name,
                        r.mac::text AS mac,
                        r.model
                    FROM ring_pairing_requests pr
                    JOIN t_user_app_telegram u
                      ON u.id = pr.telegram_user_id
                    JOIN rings r
                      ON r.id = pr.ring_id
                    WHERE pr.id = %s
                    FOR UPDATE
                    """,
                    (int(request_id),),
                )

                row = cur.fetchone()

                if not row:
                    return None

                row = dict(row)

                if row["status"] != "pending":
                    row["result"] = "already_decided"
                    return row

                cur.execute(
                    """
                    INSERT INTO ring_telegram_access (
                        ring_id,
                        telegram_user_id,
                        can_view,
                        can_view_history,
                        can_live,
                        can_receive_alerts,
                        can_admin,
                        active
                    )
                    VALUES (%s, %s, TRUE, TRUE, TRUE, %s, FALSE, TRUE)
                    ON CONFLICT (ring_id, telegram_user_id)
                    DO UPDATE SET
                        can_view = TRUE,
                        can_view_history = TRUE,
                        can_live = TRUE,
                        can_receive_alerts = EXCLUDED.can_receive_alerts,
                        can_admin = FALSE,
                        active = TRUE,
                        updated_at = NOW()
                    """,
                    (
                        row["ring_id"],
                        row["telegram_user_id"],
                        bool(PAIRING_DEFAULT_ALERTS),
                    ),
                )

                cur.execute(
                    """
                    UPDATE ring_pairing_requests
                    SET
                        status = 'approved',
                        decided_at = NOW(),
                        decided_by_telegram_id = %s
                    WHERE id = %s
                    """,
                    (
                        int(admin_telegram_id),
                        int(request_id),
                    ),
                )

                row["result"] = "approved"
                return row


def reject_pairing_request(request_id, admin_telegram_id):
    with get_connection() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        pr.id AS request_id,
                        pr.status,
                        pr.ring_id,
                        pr.telegram_user_id,
                        u.id_telegram,
                        u.firstname,
                        u.lastname,
                        u.pseudo,
                        r.name AS ring_name,
                        r.mac::text AS mac
                    FROM ring_pairing_requests pr
                    JOIN t_user_app_telegram u
                      ON u.id = pr.telegram_user_id
                    JOIN rings r
                      ON r.id = pr.ring_id
                    WHERE pr.id = %s
                    FOR UPDATE
                    """,
                    (int(request_id),),
                )

                row = cur.fetchone()

                if not row:
                    return None

                row = dict(row)

                if row["status"] != "pending":
                    row["result"] = "already_decided"
                    return row

                cur.execute(
                    """
                    UPDATE ring_pairing_requests
                    SET
                        status = 'rejected',
                        decided_at = NOW(),
                        decided_by_telegram_id = %s
                    WHERE id = %s
                    """,
                    (
                        int(admin_telegram_id),
                        int(request_id),
                    ),
                )

                row["result"] = "rejected"
                return row

def db_start_live_session(telegram_user_id, ring_id, chat_id, message_id):
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=LIVE_SESSION_MINUTES
    )
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO telegram_live_sessions (
                    telegram_user_id,
                    ring_id,
                    chat_id,
                    telegram_message_id,
                    active,
                    started_at,
                    last_update_at,
                    expires_at
                )
                VALUES (%s,%s,%s,%s,TRUE,NOW(),NOW(),%s)
                ON CONFLICT (telegram_user_id, ring_id, chat_id)
                DO UPDATE SET
                    telegram_message_id=EXCLUDED.telegram_message_id,
                    active=TRUE,
                    started_at=NOW(),
                    last_update_at=NOW(),
                    expires_at=EXCLUDED.expires_at
                """,
                (
                    int(telegram_user_id),
                    int(ring_id),
                    int(chat_id),
                    int(message_id),
                    expires_at,
                ),
            )


def db_stop_live_session(telegram_user_id, ring_id, chat_id):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE telegram_live_sessions
                SET active=FALSE, last_update_at=NOW()
                WHERE telegram_user_id=%s
                  AND ring_id=%s
                  AND chat_id=%s
                """,
                (
                    int(telegram_user_id),
                    int(ring_id),
                    int(chat_id),
                ),
            )



async def stop_live_sessions_for_chat(
    chat_id,
    *,
    ring_id=None,
    bot=None,
):
    """
    Arrête proprement les sessions LIVE actives d'un chat.

    Utilisé quand l'utilisateur quitte volontairement le LIVE :
      - Mes rings
      - Historique
      - retour écran Ring
      - /start
      - /rings

    IMPORTANT :
    une perte BLE / HORS PORTEE n'appelle jamais cette fonction.
    Le LIVE continue donc normalement pendant une perte de portée.
    """
    chat_id = int(chat_id)
    wanted_ring_id = (
        int(ring_id)
        if ring_id is not None
        else None
    )

    stopped = []

    with live_sessions_lock:
        for key, session in list(
            live_sessions.items()
        ):
            session_chat_id = int(
                session.get("chat_id")
            )
            session_ring_id = int(
                session.get("ring_id")
            )

            if session_chat_id != chat_id:
                continue

            if (
                wanted_ring_id is not None
                and session_ring_id
                != wanted_ring_id
            ):
                continue

            stopped.append(
                dict(session)
            )

            live_sessions.pop(
                key,
                None,
            )

    for session in stopped:
        try:
            db_stop_live_session(
                session["telegram_user_id"],
                session["ring_id"],
                session["chat_id"],
            )
        except Exception:
            log.exception(
                "Erreur arrêt LIVE DB chat=%s ring=%s",
                session.get("chat_id"),
                session.get("ring_id"),
            )

        # Si l'avertissement "< 5 min" a déjà été envoyé,
        # il devient lui aussi obsolète quand l'utilisateur quitte LIVE.
        warning_message_id = session.get(
            "warning_message_id"
        )

        if (
            bot is not None
            and warning_message_id
        ):
            try:
                await bot.delete_message(
                    chat_id=session["chat_id"],
                    message_id=warning_message_id,
                )
            except Exception:
                # Un message déjà supprimé n'est pas une erreur fonctionnelle.
                pass

    return len(stopped)


def db_extend_live_session(
    telegram_user_id,
    ring_id,
    chat_id,
    minutes,
):
    """
    Prolonge la session LIVE en DB sans remettre started_at à zéro.
    """
    minutes = max(1, int(minutes))

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE telegram_live_sessions
                SET
                    active=TRUE,
                    last_update_at=NOW(),
                    expires_at=NOW() + (%s || ' minutes')::interval
                WHERE telegram_user_id=%s
                  AND ring_id=%s
                  AND chat_id=%s
                """,
                (
                    minutes,
                    int(telegram_user_id),
                    int(ring_id),
                    int(chat_id),
                ),
            )


# ============================================================
# MQTT
# ============================================================

def refresh_rings_cache(force=False):
    global rings_cache_at
    now = time.monotonic()

    with rings_cache_lock:
        if not force and rings_cache and now - rings_cache_at < 60:
            return list(rings_cache)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id AS ring_id,
                    name AS ring_name,
                    mac::text AS mac,
                    mqtt_base_topic
                FROM rings
                WHERE active=TRUE
                  AND mqtt_base_topic IS NOT NULL
                """
            )
            rows = [dict(r) for r in cur.fetchall()]

    rows.sort(
        key=lambda r: len(r.get("mqtt_base_topic") or ""),
        reverse=True,
    )

    with rings_cache_lock:
        rings_cache[:] = rows
        rings_cache_at = now

    return rows


def ring_from_topic(topic):
    for ring in refresh_rings_cache():
        base = (ring.get("mqtt_base_topic") or "").rstrip("/")
        if base and (topic == base or topic.startswith(base + "/")):
            return ring, topic[len(base):].lstrip("/")
    return None, None


def normalize_metric(metric_path):
    metric = (metric_path or "").split("/")[-1].strip().lower()
    return {
        "heart-rate": "heart_rate",
        "heart_rate": "heart_rate",
        "spo2": "spo2",
        "hrv": "hrv",
        "fatigue": "fatigue",
        "health-check": "health_check",
        "health_check": "health_check",
        "battery": "battery",
        "steps": "steps",
        "rssi": "rssi",
        "temperature": "temperature",
        "outside": "outside",
        "wear": "wear_status",
        "wear-status": "wear_status",
        "wear_status": "wear_status",
        "wearing": "wear_status",
    }.get(metric, metric)


def extract_samples(payload):
    """Récupère la liste de samples exactement comme le dashboard DANY."""
    candidates = []

    raw = payload.get("value")
    if isinstance(raw, dict):
        candidates.extend([raw.get("samples"), raw.get("value")])

    candidates.extend([payload.get("samples"), raw])

    for candidate in candidates:
        if isinstance(candidate, (list, tuple)):
            out = []
            for item in candidate:
                if isinstance(item, (int, float)):
                    f = float(item)
                    out.append(int(f) if f.is_integer() else f)
            if out:
                return out

    return None


def numeric_value(payload):
    """Valeur simple pour batterie/pas/RSSI ou repli technique."""
    raw = payload.get("value")

    if isinstance(raw, (int, float)):
        return float(raw)

    if isinstance(raw, dict):
        for key in ("last", "value", "value_median", "median"):
            v = raw.get(key)
            if isinstance(v, (int, float)):
                return float(v)

    for key in ("last", "value2", "value_median", "median"):
        v = payload.get(key)
        if isinstance(v, (int, float)):
            return float(v)

    return None




def _recent_measurement_failed_count(state, now_epoch):
    count = 0

    for metric in PHYSIO_METRICS:
        failed_at = state.get(
            f"{metric}_measurement_failed_epoch"
        )

        if not isinstance(
            failed_at,
            (int, float),
        ):
            continue

        if (
            now_epoch - float(failed_at)
            <= WEAR_FAILURE_WINDOW_SECONDS
        ):
            count += 1

    return count


def _set_inferred_wear(state, value, reason, timestamp):
    state["wear_inferred"] = value
    state["wear_inferred_reason"] = reason
    state["wear_inferred_at"] = timestamp


def update_live_state(ring_id, metric, payload):
    """
    Etat unique Telegram.

    Priorité :
      HORS PORTEE
      > ONLINE NON PORTE
      > ONLINE PORTE

    L'échec measurement_failed n'est pas interprété comme une perte BLE.
    Si plusieurs capteurs physiologiques échouent dans la même fenêtre,
    on considère la bague ONLINE mais NON PORTEE.
    """
    now_dt = datetime.now(timezone.utc)
    now_iso = now_dt.isoformat()
    now_epoch = now_dt.timestamp()

    with live_state_lock:
        state = live_state.setdefault(
            int(ring_id),
            {
                "ring_id": int(ring_id),
                "online": True,
                "outside": False,
            },
        )

        was_outside = bool(
            state.get("outside")
        )

        timestamp = (
            payload.get("timestamp")
            or now_iso
        )

        state["updated_at"] = timestamp

        status = str(
            payload.get("status") or ""
        ).strip().lower()

        reason = payload.get("reason")
        reason_text = str(
            reason or ""
        ).strip().lower()

        unit = payload.get("unit")

        fault_code = str(
            payload.get("fault_code")
            or payload.get("reason")
            or ""
        ).strip().lower()

        # ----------------------------------------------------
        # 1) HORS PORTEE
        # ----------------------------------------------------
        if metric == "outside" or fault_code in (
            "device_not_found",
            "device_out_of_range",
        ):
            state["online"] = False
            state["outside"] = True
            state["ble_status"] = (
                fault_code
                or "device_out_of_range"
            )
            state["outside_timestamp"] = timestamp

            for sensor in PHYSIO_METRICS:
                state[f"{sensor}_status"] = "hors_portee"
                state[f"{sensor}_reason"] = state["ble_status"]
                state[f"{sensor}_timestamp"] = timestamp
                state[f"{sensor}_samples"] = None

            return {
                "outside_transition":
                    not was_outside,
                "back_online_transition": False,
            }

        # Une donnée BLE valide prouve que la bague est de nouveau joignable.
        #
        # IMPORTANT :
        # il faut aussi effacer l'ancien ble_status=device_out_of_range.
        # Sinon presence_line() peut continuer à afficher HORS PORTEE alors
        # que Batterie / HR / SpO2 viennent réellement d'arriver.
        back_online_transition = was_outside

        state["online"] = True
        state["outside"] = False
        state["ble_status"] = "ok"
        state["outside_timestamp"] = None
        state["last_ble_seen_at"] = timestamp

        # ----------------------------------------------------
        # 2) PORT explicite
        # ----------------------------------------------------
        if metric == "wear_status":
            wear_value = (
                payload.get("wear_status")
                if payload.get("wear_status")
                is not None
                else payload.get("value")
            )

            if wear_value is not None:
                wear_text = str(
                    wear_value
                ).strip().lower()

                state["wear_status"] = wear_text

                if _is_not_worn(wear_text):
                    _set_inferred_wear(
                        state,
                        "not_worn",
                        "wear_status",
                        timestamp,
                    )
                else:
                    _set_inferred_wear(
                        state,
                        "worn",
                        "wear_status",
                        timestamp,
                    )

            return {
                "outside_transition": False,
                "back_online_transition": back_online_transition,
            }

        if "wear_status" in payload:
            state["wear_status"] = str(
                payload.get("wear_status")
            ).strip().lower()

        # ----------------------------------------------------
        # 3) CHARGE
        # ----------------------------------------------------
        if metric == "battery":
            value = numeric_value(payload)

            if value is not None:
                state["battery"] = value

            # Timestamp de CETTE mesure batterie.
            state["battery_timestamp"] = timestamp

            if "charging" in payload:
                charging = bool(
                    payload.get("charging")
                )
                state["charging"] = charging

                if charging:
                    _set_inferred_wear(
                        state,
                        "not_worn",
                        "charging",
                        timestamp,
                    )

            return {
                "outside_transition": False,
                "back_online_transition": back_online_transition,
            }

        # ----------------------------------------------------
        # Normalisation état mesure
        # ----------------------------------------------------
        if (
            status in (
                "en_cours",
                "encours",
                "in_progress",
                "progress",
                "measuring",
            )
            or reason_text
            == "measurement_started"
        ):
            status = "en_cours"

        sampled_metric = metric in (
            "heart_rate",
            "spo2",
            "hrv",
            "fatigue",
            "health_check",
            "temperature",
        )

        if sampled_metric:
            state[f"{metric}_status"] = (
                status or "ok"
            )
            state[f"{metric}_reason"] = reason
            state[f"{metric}_timestamp"] = timestamp

            if unit is not None:
                state[f"{metric}_unit"] = unit

            if status == "en_cours":
                state[f"{metric}_samples"] = None

                return {
                    "outside_transition": False,
                }

            samples = extract_samples(payload)
            value = numeric_value(payload)

            if samples is not None:
                state[f"{metric}_samples"] = samples

            if value is not None:
                state[metric] = value

            # ------------------------------------------------
            # measurement_failed : la bague répond,
            # donc ce n'est PAS "non connecté".
            # ------------------------------------------------
            if (
                metric in PHYSIO_METRICS
                and reason_text == "measurement_failed"
            ):
                state[
                    f"{metric}_measurement_failed_epoch"
                ] = now_epoch

                failed_count = (
                    _recent_measurement_failed_count(
                        state,
                        now_epoch,
                    )
                )

                if (
                    failed_count
                    >= WEAR_FAILURE_THRESHOLD
                ):
                    _set_inferred_wear(
                        state,
                        "not_worn",
                        (
                            f"{failed_count}_"
                            "measurement_failed"
                        ),
                        timestamp,
                    )

                return {
                    "outside_transition": False,
                }

            # ------------------------------------------------
            # Une vraie mesure physiologique OK prouve
            # que la bague est portée.
            # ------------------------------------------------
            if (
                metric in PHYSIO_METRICS
                and status == "ok"
                and (
                    samples
                    or value is not None
                )
            ):
                state[
                    f"{metric}_measurement_failed_epoch"
                ] = None

                _set_inferred_wear(
                    state,
                    "worn",
                    f"{metric}_ok",
                    timestamp,
                )

                state[
                    "last_measurement_at"
                ] = timestamp

            elif status == "ok":
                state[
                    "last_measurement_at"
                ] = timestamp

            return {
                "outside_transition": False,
                "back_online_transition": back_online_transition,
            }

        # ----------------------------------------------------
        # Valeurs simples
        # ----------------------------------------------------
        value = numeric_value(payload)

        if metric == "rssi" and value is not None:
            state["rssi"] = value

        elif metric == "steps":
            if isinstance(
                payload.get("steps"),
                (int, float),
            ):
                state["steps"] = float(
                    payload["steps"]
                )

            elif value is not None:
                state["steps"] = value

            if isinstance(
                payload.get("distance_m"),
                (int, float),
            ):
                state["distance_m"] = float(
                    payload["distance_m"]
                )

            if isinstance(
                payload.get("calories_raw"),
                (int, float),
            ):
                state["calories_raw"] = float(
                    payload["calories_raw"]
                )

        return {
            "outside_transition": False,
            "back_online_transition": back_online_transition,
        }

def mqtt_on_connect(client, userdata, flags, reason_code, properties=None):
    log.info("MQTT connecté : %s", reason_code)

    # Base indisponible au moment de la connexion : ne pas tuer le thread MQTT
    # (sinon plus aucun message ni mesure jusqu'au redémarrage du bot).
    try:
        refresh_rings_cache(force=True)
    except Exception:
        log.exception("Cache des bagues (PostgreSQL) indisponible à la connexion MQTT")

    client.subscribe(MQTT_TOPIC)
    log.info("MQTT abonnement : %s", MQTT_TOPIC)

    # TV Android : état, résultats et commandes des autres lanceurs (QRing Admin)
    android_topic = f"{QRING_PREFIX}/+/+"
    if android_topic != MQTT_TOPIC and MQTT_TOPIC != f"{QRING_PREFIX}/#":
        client.subscribe(android_topic, qos=1)
        log.info("MQTT abonnement : %s", android_topic)



ANDROID_TOPIC_RE = re.compile(r"^[0-9A-Fa-f]{12}$")


def is_android_topic(topic):
    """
    Format de l'app Android (TV) : <préfixe>/<MAC sans ':'>/<type>.
    Ces messages sont traités par QRing Admin (état, base, mesures) :
    l'ancien traitement LIVE de la Pi400 les ignore.
    """
    base = QRING_PREFIX.split("/")
    parts = topic.split("/")
    rest = parts[len(base):] if parts[:len(base)] == base else []
    return len(rest) == 2 and bool(ANDROID_TOPIC_RE.match(rest[0]))


def is_gateway_topic(topic):
    """eis/colmi/gateway/<TV>/… : statut des TV (géré via les topics des bagues)."""
    base = QRING_PREFIX.split("/")
    parts = topic.split("/")
    return parts[:len(base)] == base and len(parts) > len(base) and parts[len(base)] == "gateway"


def mqtt_on_message(client, userdata, msg):
    if is_gateway_topic(msg.topic):
        return

    if is_android_topic(msg.topic):
        try:
            payload = json.loads(msg.payload.decode("utf-8", errors="replace"))
            if isinstance(payload, dict):
                mac12, sub = msg.topic.split("/")[-2:]
                handle_android_message(mac12, sub, payload)
        except Exception:
            log.exception("Message TV illisible : %s", msg.topic)
        return

    try:
        ring, metric_path = ring_from_topic(msg.topic)

        if not ring:
            return

        payload = json.loads(
            msg.payload.decode(
                "utf-8",
                errors="replace",
            )
        )

        metric = normalize_metric(metric_path)

        transition = update_live_state(
            ring["ring_id"],
            metric,
            payload,
        ) or {}

        raw_status = str(
            payload.get("status") or ""
        ).strip().lower()

        raw_reason = str(
            payload.get("reason") or ""
        ).strip().lower()

        is_measurement_transition = (
            raw_status in (
                "en_cours",
                "encours",
                "in_progress",
                "progress",
                "measuring",
                "ok",
                "non_connecte",
                "error",
                "failed",
            )
            or raw_reason == "measurement_started"
            or metric == "outside"
        )

        if is_measurement_transition:
            log.info(
                "LIVE MQTT ring=%s metric=%s status=%s reason=%s",
                ring["ring_id"],
                metric,
                raw_status,
                raw_reason,
            )

        schedule_ring_live_update(
            ring["ring_id"],
            force=is_measurement_transition,
        )

        # L'écran intermédiaire de la bague est lui aussi temps réel.
        schedule_ring_overview_update(
            ring["ring_id"],
            force=is_measurement_transition,
        )

        # Une seule notification par transition vers hors portée.
        if transition.get("outside_transition"):
            schedule_outside_alert(
                ring["ring_id"],
                ring["ring_name"],
                payload,
            )

        # Dès qu'une NOUVELLE donnée valide prouve le retour ONLINE,
        # supprimer le warning HORS PORTÉE devenu obsolète dans le chat.
        if transition.get("back_online_transition"):
            schedule_clear_outside_alerts(
                ring["ring_id"]
            )

    except Exception:
        log.exception(
            "Erreur MQTT topic=%s",
            msg.topic,
        )

def start_mqtt():
    global mqtt_client_ref

    # Identifiant unique : l'ancien bot DANY (dany_telegram_bot) ne peut pas nous déconnecter
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"qring_telegram_bot_{uuid.uuid4().hex[:6]}",
    )

    if MQTT_USER:
        client.username_pw_set(
            MQTT_USER,
            MQTT_PASSWORD or None,
        )

    client.on_connect = mqtt_on_connect
    client.on_message = mqtt_on_message

    client.connect_async(
        MQTT_HOST,
        MQTT_PORT,
        keepalive=60,
    )
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    client.loop_start()

    mqtt_client_ref = client
    return client


# ============================================================
# Affichage
# ============================================================

def fmt_num(value):
    if value is None:
        return "—"
    try:
        f = float(value)
        if abs(f - round(f)) < 1e-9:
            return str(int(round(f)))
        return f"{f:.1f}"
    except Exception:
        return str(value)


def fmt_time(value):
    if not value:
        return "—"

    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )
        except Exception:
            return value

    try:
        return value.astimezone().strftime("%d/%m %H:%M:%S")
    except Exception:
        return str(value)


def fmt_samples(samples):
    if not samples:
        return "—"
    return "[" + ", ".join(fmt_num(v) for v in samples) + "]"




def sensor_block(state, metric, label, default_unit=""):
    status = str(
        state.get(f"{metric}_status") or ""
    ).strip().lower()

    reason = state.get(
        f"{metric}_reason"
    )
    reason_text = str(
        reason or ""
    ).strip().lower()

    unit = (
        state.get(f"{metric}_unit")
        or default_unit
    )

    timestamp = state.get(
        f"{metric}_timestamp"
    )

    samples = state.get(
        f"{metric}_samples"
    )

    lines = [label]

    # HORS PORTEE : priorité absolue.
    if status in (
        "hors_portee",
        "outside",
        "device_not_found",
        "device_out_of_range",
    ):
        lines.append(
            "🟡 Hors portée / Out of range"
        )

        if timestamp:
            lines.append(
                f"Timestamp : {fmt_time(timestamp)}"
            )

        return lines

    # MESURE EN COURS.
    if status in (
        "en_cours",
        "encours",
        "in_progress",
        "progress",
        "measuring",
    ):
        lines.append(
            "🟠 En cours / In progress"
        )
        lines.append(
            "En attente de données / Waiting for data"
        )

    # MESURE OK.
    elif status == "ok":
        lines.append(
            "🟢 Terminé / Done — OK"
        )
        lines.append(
            f"Valeur : {fmt_samples(samples)}"
        )

    # measurement_failed + inférence non porté.
    elif (
        reason_text == "measurement_failed"
        and inferred_not_worn(state)
    ):
        lines.append(
            "🟠 Mesure impossible — Bague non portée / "
            "Measurement failed — Ring not worn"
        )
        lines.append(
            "Valeur : —"
        )

    # measurement_failed sans preuve suffisante de retrait.
    elif reason_text == "measurement_failed":
        lines.append(
            "🔴 Échec de mesure / Measurement failed"
        )
        lines.append(
            "Valeur : —"
        )

    elif status in (
        "non_connecte",
        "error",
        "failed",
    ):
        lines.append(
            "🔴 Erreur capteur / Sensor error"
        )

        if reason:
            lines.append(
                f"Raison / Reason : {reason}"
            )

        lines.append(
            "Valeur : —"
        )

    else:
        # HRV / température peuvent ne pas être disponibles.
        if samples:
            lines.append(
                f"Valeur : {fmt_samples(samples)}"
            )
        else:
            simple_value = state.get(metric)

            lines.append(
                f"Valeur : {fmt_num(simple_value)}"
            )

    if unit:
        lines.append(
            f"Unité : {unit}"
        )

    if timestamp:
        lines.append(
            f"Timestamp : {fmt_time(timestamp)}"
        )

    return lines

def _is_not_worn(value):
    text = str(value or "").strip().lower()

    return text in (
        "not_worn",
        "not-worn",
        "unworn",
        "removed",
        "off_wrist",
        "off-wrist",
        "non_porte",
        "non-porté",
        "non_porté",
        "false",
        "0",
        "no",
    )



def inferred_not_worn(state):
    """
    Retourne True si l'état fonctionnel conclut NON PORTE.
    """
    if state.get("charging") is True:
        return True

    inferred = str(
        state.get("wear_inferred") or ""
    ).strip().lower()

    if inferred == "not_worn":
        return True

    if _is_not_worn(
        state.get("wear_status")
    ):
        return True

    return False


def presence_line(state):
    """
    Trois états client :

      🟢 ONLINE — PORTÉ / WORN
      🟠 ONLINE — NON PORTÉ / NOT WORN
      🟡 HORS PORTÉE / OUT OF RANGE
    """
    ble_status = str(
        state.get("ble_status") or ""
    ).strip().lower()

    outside = (
        bool(state.get("outside"))
        or state.get("online") is False
        or ble_status in (
            "device_not_found",
            "device_out_of_range",
            "outside",
            "hors_portee",
        )
    )

    if outside:
        return (
            "🟡 HORS PORTÉE / "
            "OUT OF RANGE"
        )

    if inferred_not_worn(state):
        return (
            "🟠 ONLINE — NON PORTÉ / "
            "NOT WORN"
        )

    return (
        "🟢 ONLINE — PORTÉ / WORN"
    )


def charging_text(state):
    charging = state.get("charging")

    if charging is True:
        return "En charge / Charging"

    if charging is False:
        return (
            "Débranchée du chargeur / "
            "Not charging"
        )

    return "—"


def format_ring_overview(access, state):
    """
    Ecran intermédiaire visible après avoir choisi une bague.

    Cet écran reste en temps réel tant que l'utilisateur ne quitte
    pas cette vue :
      - statut ONLINE / RETIREE / OUT OF RANGE
      - batterie
      - statut de charge
      - timestamp exact de la batterie
    """
    return "\n".join(
        [
            f"💍 {access['ring_name']}",
            "",
            presence_line(state),
            f"MAC : {access['mac']}",
            "",
            f"🔋 Batterie : {fmt_num(state.get('battery'))} %",
            f"🔌 Statut : {charging_text(state)}",
            (
                "🕒 Batterie / Battery timestamp : "
                f"{fmt_time(state.get('battery_timestamp'))}"
            ),
            "",
            "Choisis une fonction / Choose a function:",
        ]
    )


def format_live(ring_name, state):
    charging_txt = charging_text(state)

    lines = [
        f"💍 {ring_name}",
        "",
        presence_line(state),
        "",
        f"🔋 Batterie : {fmt_num(state.get('battery'))} %",
        f"🔌 Statut : {charging_txt}",
        (
            "🕒 Batterie / Battery timestamp : "
            f"{fmt_time(state.get('battery_timestamp'))}"
        ),
        "",
    ]

    for metric, label, unit in (
        (
            "heart_rate",
            "❤️ Rythme Cardiaque (HR)",
            "bpm",
        ),
        (
            "spo2",
            "🫁 SpO₂",
            "%",
        ),
        (
            "fatigue",
            "⚡ Fatigue",
            "index",
        ),
        (
            "health_check",
            "🩺 Health-check",
            "index",
        ),
        (
            "hrv",
            "💓 HRV",
            "",
        ),
        (
            "temperature",
            "🌡 Température",
            "°C",
        ),
    ):
        lines.extend(
            sensor_block(
                state,
                metric,
                label,
                unit,
            )
        )
        lines.append("")

    lines.extend(
        [
            f"🚶 Pas : {fmt_num(state.get('steps'))}",
            f"📏 Distance : {fmt_num(state.get('distance_m'))} m",
            f"🔥 Calories : {fmt_num(state.get('calories_raw'))}",
            f"📶 RSSI : {fmt_num(state.get('rssi'))} dBm",
            f"💍 Port : {state.get('wear_status') or '—'}",
            f"Mise à jour : {fmt_time(state.get('updated_at'))}",
        ]
    )

    return "\n".join(lines)

def format_history(ring_name, rows, hours):
    period = {
        1: "1 heure",
        24: "24 heures",
        168: "7 jours",
        720: "30 jours",
    }.get(hours, f"{hours} h")

    lines = [
        f"📊 Historique — {ring_name}",
        f"Période : {period}",
        "",
    ]

    if not rows:
        lines.append("Aucune donnée sur cette période.")
        return "\n".join(lines)

    for row in rows:
        label = METRIC_LABEL.get(row["metric"], row["metric"])
        lines.append(label)

        if row["samples_count"]:
            lines.append(
                "  dernier={}  moy={}  min={}  max={}".format(
                    fmt_num(row["last_value"]),
                    fmt_num(row["avg_value"]),
                    fmt_num(row["min_value"]),
                    fmt_num(row["max_value"]),
                )
            )
        else:
            lines.append("  aucune valeur valide")

        if row["error_count"]:
            lines.append(f"  erreurs={row['error_count']}")

        lines.append("")

    return "\n".join(lines).strip()


# ============================================================
# LIVE Telegram
# ============================================================


def live_keyboard(ring_id):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🔄 Actualiser / Refresh",
                    callback_data=(
                        f"refreshlive:{ring_id}"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    "⏹ Arrêter LIVE / Stop LIVE",
                    callback_data=(
                        f"stoplive:{ring_id}"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    "📊 Historique / History",
                    callback_data=(
                        f"history:{ring_id}"
                    ),
                ),
                InlineKeyboardButton(
                    "⬅️ Mes rings",
                    callback_data="rings",
                ),
            ],
        ]
    )


def clear_ring_overview_sessions(chat_id, ring_id=None):
    """
    Arrête les mises à jour automatiques de l'écran Ring.

    On l'appelle dès que l'utilisateur quitte cet écran
    (LIVE, historique, liste des rings, etc.).
    """
    chat_id = int(chat_id)

    with ring_overview_sessions_lock:
        keys = [
            key
            for key in ring_overview_sessions
            if key[0] == chat_id
            and (
                ring_id is None
                or key[1] == int(ring_id)
            )
        ]

        for key in keys:
            ring_overview_sessions.pop(
                key,
                None,
            )


def register_ring_overview_session(
    *,
    chat_id,
    message_id,
    access,
):
    """
    Enregistre l'écran de détail d'une bague pour qu'il soit
    rafraîchi automatiquement depuis MQTT.
    """
    chat_id = int(chat_id)
    ring_id = int(access["ring_id"])

    # Un seul écran overview actif par chat.
    clear_ring_overview_sessions(
        chat_id
    )

    with ring_overview_sessions_lock:
        ring_overview_sessions[
            (
                chat_id,
                ring_id,
            )
        ] = {
            "chat_id": chat_id,
            "message_id": int(message_id),
            "ring_id": ring_id,
            "access": dict(access),
            "last_edit": 0.0,
        }


def schedule_ring_overview_update(
    ring_id,
    force=False,
):
    """
    Met à jour l'écran Ring lorsqu'une nouvelle donnée MQTT arrive.

    Le statut OUT OF RANGE disparaît donc immédiatement à la réception
    d'une nouvelle batterie / mesure valide, exactement comme dans LIVE.
    """
    if (
        telegram_loop is None
        or telegram_app is None
    ):
        return

    ring_id = int(ring_id)

    with ring_overview_sessions_lock:
        sessions = [
            dict(session)
            for (
                _chat_id,
                rid,
            ), session in (
                ring_overview_sessions.items()
            )
            if rid == ring_id
        ]

    now = time.monotonic()

    for session in sessions:
        key = (
            session["chat_id"],
            session["ring_id"],
        )

        with ring_overview_sessions_lock:
            original = (
                ring_overview_sessions.get(
                    key
                )
            )

            if not original:
                continue

            if (
                not force
                and now
                - original.get(
                    "last_edit",
                    0,
                )
                < RING_OVERVIEW_REFRESH_SECONDS
            ):
                continue

            original["last_edit"] = now

        asyncio.run_coroutine_threadsafe(
            refresh_ring_overview_message(
                session
            ),
            telegram_loop,
        )


async def refresh_ring_overview_message(
    session,
):
    with live_state_lock:
        state = dict(
            live_state.get(
                session["ring_id"],
                {},
            )
        )

    access = session["access"]

    try:
        await telegram_app.bot.edit_message_text(
            chat_id=session["chat_id"],
            message_id=session["message_id"],
            text=format_ring_overview(
                access,
                state,
            ),
            reply_markup=ring_keyboard(
                access
            ),
        )

    except BadRequest as exc:
        if (
            "message is not modified"
            not in str(exc).lower()
        ):
            log.warning(
                "Telegram ring overview : %s",
                exc,
            )

    except RetryAfter as exc:
        log.warning(
            "Rate limit Telegram overview : %s",
            exc.retry_after,
        )

    except Forbidden:
        clear_ring_overview_sessions(
            session["chat_id"],
            session["ring_id"],
        )

    except Exception:
        log.exception(
            "Erreur refresh ring overview"
        )


def schedule_ring_live_update(ring_id, force=False):
    """
    Rafraîchit le message LIVE.

    force=True est utilisé pour les changements d'état des mesures
    (en_cours / ok / non_connecte / erreur). Ils ne doivent jamais être
    masqués par le throttle général LIVE_REFRESH_SECONDS.
    """
    if telegram_loop is None:
        return

    with live_sessions_lock:
        sessions = [
            dict(s)
            for (_, rid), s in live_sessions.items()
            if rid == int(ring_id)
        ]

    now = time.monotonic()

    for session in sessions:
        key = (session["chat_id"], session["ring_id"])

        with live_sessions_lock:
            original = live_sessions.get(key)
            if not original:
                continue

            if (
                not force
                and now - original.get("last_edit", 0) < LIVE_REFRESH_SECONDS
            ):
                continue

            original["last_edit"] = now

        asyncio.run_coroutine_threadsafe(
            refresh_live_message(session),
            telegram_loop,
        )


async def refresh_live_message(session):
    with live_state_lock:
        state = dict(
            live_state.get(session["ring_id"], {})
        )

    text = format_live(
        session["ring_name"],
        state,
    )

    try:
        await telegram_app.bot.edit_message_text(
            chat_id=session["chat_id"],
            message_id=session["message_id"],
            text=text,
            reply_markup=live_keyboard(session["ring_id"]),
        )
    except BadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            log.warning("Telegram : %s", exc)
    except RetryAfter as exc:
        log.warning("Rate limit Telegram : %s", exc.retry_after)
    except Forbidden:
        log.warning("Bot bloqué / chat interdit")
    except Exception:
        log.exception("Erreur refresh LIVE")



# ============================================================
# NOTIFICATIONS TELEGRAM
# ============================================================

def is_global_admin(telegram_id):
    try:
        return int(telegram_id) in TELEGRAM_ADMIN_IDS
    except Exception:
        return False


async def send_assignment_notification_bot(
    bot_api,
    *,
    chat_id,
    ring_id,
    ring_name,
    mac,
    first_name=None,
):
    hello = f" {first_name}" if first_name else ""

    text = (
        f"✅ Nouvelle bague affectée / New ring assigned{hello}\n\n"
        f"💍 {ring_name}\n"
        f"📡 MAC : {mac}\n\n"
        "La bague est maintenant affectée à ton compte.\n"
        "The ring is now assigned to your account."
    )

    markup = InlineKeyboardMarkup(
        [[
            InlineKeyboardButton(
                "💍 Ouvrir la bague / Open ring",
                callback_data=f"ring:{ring_id}",
            )
        ]]
    )

    await bot_api.send_message(
        chat_id=int(chat_id),
        text=text,
        reply_markup=markup,
    )


async def send_unassignment_notification_bot(
    bot_api,
    *,
    chat_id,
    ring_name,
    mac,
):
    await bot_api.send_message(
        chat_id=int(chat_id),
        text=(
            "ℹ️ Bague désaffectée / Ring unassigned\n\n"
            f"💍 {ring_name}\n"
            f"📡 MAC : {mac}\n\n"
            "Cette bague n'est plus affectée à ton compte.\n"
            "This ring is no longer assigned to your account."
        ),
    )



def schedule_clear_outside_alerts(ring_id):
    """
    Supprime du chat les anciens messages HORS PORTÉE de cette bague
    dès que la bague redevient ONLINE.
    """
    if telegram_loop is None or telegram_app is None:
        return

    asyncio.run_coroutine_threadsafe(
        clear_outside_alerts(
            ring_id
        ),
        telegram_loop,
    )


async def clear_outside_alerts(ring_id):
    ring_id = int(ring_id)

    with outside_alert_messages_lock:
        targets = [
            (
                chat_id,
                message_id,
            )
            for (
                rid,
                chat_id,
            ), message_id
            in outside_alert_messages.items()
            if rid == ring_id
        ]

    for chat_id, message_id in targets:
        try:
            await telegram_app.bot.delete_message(
                chat_id=int(chat_id),
                message_id=int(message_id),
            )

        except BadRequest as exc:
            # Message déjà supprimé / trop ancien / introuvable :
            # on nettoie quand même notre cache.
            log.info(
                "Suppression warning HORS PORTEE chat=%s msg=%s : %s",
                chat_id,
                message_id,
                exc,
            )

        except Forbidden:
            log.warning(
                "Suppression warning impossible, bot bloqué chat=%s",
                chat_id,
            )

        except Exception:
            log.exception(
                "Erreur suppression warning HORS PORTEE chat=%s",
                chat_id,
            )

        finally:
            with outside_alert_messages_lock:
                outside_alert_messages.pop(
                    (
                        ring_id,
                        int(chat_id),
                    ),
                    None,
                )


def schedule_outside_alert(
    ring_id,
    ring_name,
    payload,
):
    if telegram_loop is None or telegram_app is None:
        return

    asyncio.run_coroutine_threadsafe(
        send_outside_alert(
            ring_id,
            ring_name,
            payload,
        ),
        telegram_loop,
    )


async def send_outside_alert(
    ring_id,
    ring_name,
    payload,
):
    try:
        recipients = get_alert_chat_ids(
            ring_id
        )

        if not recipients:
            return

        reason = (
            payload.get("fault_code")
            or payload.get("reason")
            or "device_out_of_range"
        )

        timestamp = (
            payload.get("timestamp")
            or datetime.now(
                timezone.utc
            ).isoformat()
        )

        text = (
            f"⚠️ {ring_name}\n\n"
            "🟡 HORS PORTÉE / OUT OF RANGE\n"
            f"Code : {reason}\n"
            f"Timestamp : {fmt_time(timestamp)}"
        )

        for chat_id in recipients:
            try:
                sent = await telegram_app.bot.send_message(
                    chat_id=int(chat_id),
                    text=text,
                )

                # Mémoriser le message pour pouvoir le retirer
                # automatiquement dès le retour ONLINE.
                with outside_alert_messages_lock:
                    previous_message_id = (
                        outside_alert_messages.get(
                            (
                                int(ring_id),
                                int(chat_id),
                            )
                        )
                    )

                    outside_alert_messages[
                        (
                            int(ring_id),
                            int(chat_id),
                        )
                    ] = sent.message_id

                # Si un vieux warning de la même bague existait encore,
                # essayer de le supprimer pour éviter les doublons.
                if (
                    previous_message_id
                    and previous_message_id
                    != sent.message_id
                ):
                    try:
                        await telegram_app.bot.delete_message(
                            chat_id=int(chat_id),
                            message_id=int(previous_message_id),
                        )
                    except Exception:
                        pass
            except Forbidden:
                log.warning(
                    "Alerte hors portée impossible : "
                    "bot bloqué chat=%s",
                    chat_id,
                )
            except Exception:
                log.exception(
                    "Erreur alerte outside chat=%s",
                    chat_id,
                )

    except Exception:
        log.exception(
            "Erreur préparation alerte hors portée"
        )


async def notify_pairing_admins(
    context,
    request_row,
    tg_user,
):
    if not TELEGRAM_ADMIN_IDS:
        log.warning(
            "Demande QR créée mais TELEGRAM_ADMIN_IDS est vide"
        )
        return

    user_label = (
        f"{tg_user.first_name or ''} "
        f"{tg_user.last_name or ''}"
    ).strip()

    if tg_user.username:
        user_label += f" (@{tg_user.username})"

    text = (
        "🔗 Nouvelle demande d'appariement / "
        "New pairing request\n\n"
        f"👤 {user_label or tg_user.id}\n"
        f"Telegram ID : {tg_user.id}\n\n"
        f"💍 {request_row['ring_name']}\n"
        f"📡 MAC : {request_row['mac']}\n\n"
        "Autoriser cette affectation ? / "
        "Approve this assignment?"
    )

    markup = InlineKeyboardMarkup(
        [[
            InlineKeyboardButton(
                "✅ Autoriser / Approve",
                callback_data=(
                    f"pairapprove:"
                    f"{request_row['request_id']}"
                ),
            ),
            InlineKeyboardButton(
                "❌ Refuser / Reject",
                callback_data=(
                    f"pairreject:"
                    f"{request_row['request_id']}"
                ),
            ),
        ]]
    )

    for admin_id in sorted(
        TELEGRAM_ADMIN_IDS
    ):
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=text,
                reply_markup=markup,
            )
        except Exception:
            log.exception(
                "Impossible de notifier admin %s",
                admin_id,
            )


# ============================================================
# Telegram handlers
# ============================================================

async def private_only(update):
    if not TELEGRAM_PRIVATE_ONLY:
        return True

    chat = update.effective_chat
    if chat and chat.type != ChatType.PRIVATE:
        if update.callback_query:
            await update.callback_query.answer(
                "Utilise le bot en message privé.",
                show_alert=True,
            )
        elif update.effective_message:
            await update.effective_message.reply_text(
                "Utilise le bot en message privé."
            )
        return False

    return True


def rings_keyboard(rings):
    rows = [
        [
            InlineKeyboardButton(
                f"💍 {r['ring_name']}",
                callback_data=f"ring:{r['ring_id']}",
            )
        ]
        for r in rings
    ]

    rows.append(
        [InlineKeyboardButton("🔄 Actualiser", callback_data="rings")]
    )
    return InlineKeyboardMarkup(rows)



def history_metric_keyboard(ring_id):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "❤️ HR",
                    callback_data=(
                        f"histmetric:{ring_id}:heart_rate"
                    ),
                ),
                InlineKeyboardButton(
                    "🫁 SpO₂",
                    callback_data=(
                        f"histmetric:{ring_id}:spo2"
                    ),
                ),
            ],
            [
                InlineKeyboardButton(
                    "⚡ Fatigue",
                    callback_data=(
                        f"histmetric:{ring_id}:fatigue"
                    ),
                ),
                InlineKeyboardButton(
                    "🩺 Health",
                    callback_data=(
                        f"histmetric:{ring_id}:health_check"
                    ),
                ),
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Ring",
                    callback_data=f"ring:{ring_id}",
                )
            ],
        ]
    )



def history_result_keyboard(
    ring_id,
    metric,
):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "⏱ Autre durée / Other period",
                    callback_data=(
                        f"histmetric:{ring_id}:"
                        f"{metric}"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Capteurs / Sensors",
                    callback_data=(
                        f"history:{ring_id}"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Ring",
                    callback_data=f"ring:{ring_id}",
                )
            ],
        ]
    )


HISTORY_METRIC_LABEL = {
    "heart_rate": "❤️ Rythme Cardiaque (HR)",
    "spo2": "🫁 SpO₂",
    "fatigue": "⚡ Fatigue",
    "health_check": "🩺 Health-check",
}


def format_metric_history(
    ring_name,
    metric,
    rows,
    hours,
):
    period = {
        1: "1 heure / 1 hour",
        24: "24 heures / 24 hours",
        168: "7 jours / 7 days",
        720: "30 jours / 30 days",
    }.get(
        int(hours),
        f"{hours} h",
    )

    label = HISTORY_METRIC_LABEL.get(
        metric,
        metric,
    )

    lines = [
        f"📊 {ring_name}",
        label,
        f"Période / Period : {period}",
        "",
    ]

    if not rows:
        lines.append(
            "Aucune donnée / No data."
        )
        return "\n".join(lines)

    # Telegram a une limite de taille.
    # 35 lignes de mesures gardent le message confortable.
    for row in rows[:35]:
        status = str(
            row.get("status") or ""
        ).lower()

        timestamp = fmt_time(
            row.get("time")
        )

        samples = row.get("samples")
        unit = row.get("unit") or ""

        if status == "ok":
            value_txt = (
                fmt_samples(samples)
                if samples
                else fmt_num(
                    row.get("value")
                )
            )

            lines.extend(
                [
                    f"🕒 {timestamp}",
                    f"Valeur : {value_txt}",
                ]
            )

            if unit:
                lines.append(
                    f"Unité : {unit}"
                )

        else:
            lines.extend(
                [
                    f"🕒 {timestamp}",
                    f"Statut : {status or '—'}",
                ]
            )

            if row.get("reason"):
                lines.append(
                    "Raison / Reason : "
                    f"{row['reason']}"
                )

        lines.append("")

    if len(rows) > 35:
        lines.append(
            f"… {len(rows) - 35} autres mesures "
            "non affichées / more records hidden."
        )

    return "\n".join(lines).strip()


# ============================================================
# TV ANDROID (QRING) : ÉTAT, MESURES À LA DEMANDE, PORT, INFOS
# ------------------------------------------------------------
# Depuis l'arrêt de la Pi400, les gateways sont les TV Android.
# Le bot est autonome : il écoute Mosquitto (eis/colmi/<MAC>/…),
# construit l'état de chaque bague et publie lui-même les commandes
# sur eis/colmi/<MAC>/cmd. QRing Admin peut être arrêté.
# La base est seulement LUE (droits, historique) : c'est QRing Admin
# qui y écrit les mesures. 
# Règle : une seule mesure à la fois par bague. Même mesure déjà en
# cours = résultat partagé ; autre mesure = refus « en cours ».
# Les commandes publiées par QRing Admin sont vues aussi (topic cmd),
# ce qui marque la bague occupée avant même la réponse de la TV.
# ============================================================

# Mesures proposées dans Telegram : clé app Android -> (bouton, libellé, unité, limite en secondes)
TG_MEASURES = {
    "hr": ("❤️ HR", "❤️ Rythme cardiaque / Heart rate", "bpm", 60),
    "spo2": ("🫁 SpO₂", "🫁 SpO₂", "%", 90),
    "hrv": ("💓 HRV", "💓 HRV", "ms", 90),
    "temp": ("🌡 Température", "🌡 Température / Temperature", "°C", 90),
}
TG_MEASURE_ORDER = ("hr", "spo2", "hrv", "temp")

# Toutes les mesures que la TV sait faire (celles lancées par l'admin comptent pour « occupée »)
ANDROID_MEASURES = ("hr", "spo2", "temp", "bp", "hrv", "stress", "all")
OTHER_MEASURE_LABELS = {
    "bp": ("🩺 Tension", "🩺 Tension / Blood pressure", "mmHg", 90),
    "stress": ("⚡ Stress", "⚡ Stress", "", 90),
    "all": ("⚡ Tout", "⚡ Mesure complète / Full check", "", 120),
}

# Marge au-delà de la limite de la TV avant d'afficher « pas de résultat »
MEASURE_MARGIN_SECONDS = 30
# Fréquence de vérification et de mise à jour du compteur
MEASURE_TICK_SECONDS = 2.0
MEASURE_EDIT_EVERY_SECONDS = 3.0

# Bouton « État » : une mesure HR sert de test de port.
# La bague n'est déclarée PORTÉE que si une vraie valeur arrive (preuve).
# Sans valeur après ce délai : « pas de signal — mal placée ou retirée ? »
# en attendant la réponse définitive de la TV.
WEAR_CHECK_SECONDS = max(5, env_int("TELEGRAM_WEAR_CHECK_SECONDS", "15"))
# Écran d'une bague mis à jour tout seul quand son état change, pendant ce délai
RING_WATCH_MINUTES = max(1, env_int("TELEGRAM_RING_WATCH_MINUTES", "30"))
RING_WATCH_MIN_EDIT_SECONDS = 3.0
# Une vérification réussie est réutilisée pendant ce délai (économise la batterie)
WEAR_REUSE_SECONDS = max(0, env_int("TELEGRAM_WEAR_REUSE_SECONDS", "120"))
# Sans statut de la TV depuis ce délai => TV hors ligne
GATEWAY_OFFLINE_AFTER = max(60, env_int("QRING_OFFLINE_AFTER", "150"))
# Une demande sans résultat est oubliée après ce délai
PENDING_FORGET_SECONDS = 150


def _qring_prefix():
    raw = os.getenv("MQTT_PREFIX") or MQTT_TOPIC
    segs = []
    for seg in raw.strip("/").split("/"):
        if seg in ("#", "+") or not seg:
            break
        segs.append(seg)
    return "/".join(segs) or "eis/colmi"


QRING_PREFIX = _qring_prefix()

ERROR_TEXT = {
    "ring_removed": "🖐 Bague retirée — veuillez porter la bague / Ring removed — please wear the ring",
    "ring_disconnected": "🟡 Hors portée / Out of range",
    "gateway_offline": "⚫ TV hors ligne / TV offline",
    "unknown": "⚫ Aucune TV ne signale cette bague / No TV reports this ring",
    "mqtt_down": "⚠️ Broker MQTT injoignable / MQTT broker unreachable",
    "timeout": "⏱ Pas de résultat / No result",
    "measure_failed": "❌ Mesure échouée / Measurement failed",
    "invalid_value": "❌ Valeur incohérente / Invalid value",
    "not_supported": "❌ Mesure non supportée par cette bague / Not supported",
    "busy": "🟠 Bague occupée / Ring busy",
    "cancelled": "⏹ Mesure annulée / Cancelled",
    "no_data": "❌ Aucune donnée / No data",
    "not_found": "🟡 Bague introuvable / Ring not found",
    "bluetooth_off": "⚫ Bluetooth de la TV désactivé / TV Bluetooth off",
}

# (chat_id, message_id) -> mesure suivie
measure_trackers = {}
MEASURE_TRACKERS_FILE = BASE_DIR / "telegram_measures.json"

# "AA:BB:CC:DD:EE:FF" -> état de la bague construit depuis MQTT
android_rings = {}
android_lock = threading.RLock()

# client MQTT (créé par start_mqtt)
mqtt_client_ref = None

_allowed_measures_column = None


def has_allowed_measures_column():
    """La colonne allowed_measures existe-t-elle ? (migration QRing Admin)"""
    global _allowed_measures_column

    if _allowed_measures_column is None:
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'ring_telegram_access'
                          AND column_name = 'allowed_measures'
                        """
                    )
                    _allowed_measures_column = cur.fetchone() is not None
        except Exception:
            log.exception("Détection allowed_measures impossible")
            return False

    return _allowed_measures_column


def access_measures_sql():
    return (
        "a.allowed_measures"
        if has_allowed_measures_column()
        else "NULL::text[] AS allowed_measures"
    )


def measure_allowed(access, key):
    """Droit général (allowed_measures NULL/vide) ou mesure cochée par l'admin."""
    if not access or not access.get("can_live"):
        return False

    allowed = access.get("allowed_measures")

    if not allowed:
        return True

    return key in allowed


def measure_info(key):
    """(bouton, libellé, unité, limite) pour n'importe quelle mesure de la TV."""
    return TG_MEASURES.get(key) or OTHER_MEASURE_LABELS.get(key) or (key.upper(), key.upper(), "", 90)


# ---------------- État des bagues depuis MQTT ----------------

def mac_upper(mac):
    return str(mac or "").strip().upper()


def mac_colon(mac12):
    m = mac12.upper()
    return ":".join(m[i:i + 2] for i in range(0, 12, 2))


def new_android_ring(mac):
    return {
        "mac": mac, "online": False, "ring": "unknown", "worn": None,
        "battery": None, "charging": False, "deviceName": "", "gateway": "",
        "firmware": "", "model": "", "statusTs": 0, "unbound": False,
        "values": {}, "errors": {}, "pending": {}, "wornCheckedTs": None,
    }


RESULT_META_KEYS = ("reqId", "type", "status", "source", "ringMac", "ringModel", "gateway", "ts", "error")


def handle_android_message(mac12, sub, p):
    """Messages de l'app Android : status, cmd (commandes d'autres lanceurs), résultats."""
    mac = mac_colon(mac12)
    t = int(time.time())

    with android_lock:
        r = android_rings.setdefault(mac, new_android_ring(mac))

        if p.get("gateway"):
            r["gateway"] = p["gateway"]
        if p.get("ringModel"):
            r["model"] = p["ringModel"]

        if sub == "cmd":
            # Commande publiée par QRing Admin (ou par nous) : la bague devient occupée tout de suite
            cmd = p.get("cmd")
            if cmd in ANDROID_MEASURES and cmd not in r["pending"]:
                r["pending"][cmd] = {"since": t, "requested": t, "reqId": p.get("reqId"), "confirmed": False}
            return

        if sub == "status":
            r.update(
                online=bool(p.get("online")),
                ring=p.get("ring", r["ring"]),
                battery=p.get("battery", r["battery"]),
                charging=bool(p.get("charging")),
                worn=p.get("worn", r["worn"]),
                deviceName=p.get("deviceName") or r["deviceName"],
                firmware=p.get("firmware") or r["firmware"],
                statusTs=t,
                unbound=p.get("ring") == "unbound",
            )
            if not r["online"] or r["ring"] != "connected":
                # TV partie ou bague déconnectée : aucune mesure ne peut aboutir
                r["pending"].clear()
                r["wornCheckedTs"] = None
            return

        st = p.get("status")

        if st in ("measuring", "searching"):
            old = r["pending"].get(sub) or {}
            r["pending"][sub] = {
                "since": t,
                "requested": old.get("requested") or t,
                "reqId": p.get("reqId") or old.get("reqId"),
                "confirmed": True,
            }
            r["errors"].pop(sub, None)
            return

        if st not in ("ok", "error"):
            return

        pnd = r["pending"].pop(sub, None) or {}
        # Début : « mesure en cours » confirmé par la TV, sinon l'envoi de la commande
        started = pnd.get("since") or pnd.get("requested")
        meta = {
            "reqId": p.get("reqId") or pnd.get("reqId"),
            "started": started,
            "dur": (t - started) if started else None,
            "ts": t,
        }

        if st == "ok":
            data = {k: v for k, v in p.items() if k not in RESULT_META_KEYS}
            r["values"][sub] = dict(meta, data=data)
            r["errors"].pop(sub, None)
            if sub == "all":
                for k in ("hr", "spo2", "temp", "hrv", "stress"):
                    if k in data:
                        r["values"][k] = dict(meta, data={"value": data[k]})
                if "sbp" in data:
                    r["values"]["bp"] = dict(meta, data={"sbp": data["sbp"], "dbp": data.get("dbp")})
            if sub == "battery":
                r["battery"] = data.get("value", r["battery"])
                r["charging"] = bool(data.get("charging"))
            if sub in ANDROID_MEASURES:
                # Une mesure réussie prouve que la bague est portée
                r["worn"] = True
                r["wornCheckedTs"] = t
        else:
            err = p.get("error") or "measure_failed"
            r["errors"][sub] = dict(meta, code=err)
            if err == "ring_removed":
                r["worn"] = False
                r["wornCheckedTs"] = None


def mark_worn_verified(mac):
    with android_lock:
        r = android_rings.get(mac_upper(mac))
        if r:
            r["worn"] = True
            r["wornCheckedTs"] = int(time.time())


def forget_stale_pending():
    t = int(time.time())
    with android_lock:
        for r in android_rings.values():
            for k, v in list(r["pending"].items()):
                if t - int(v.get("since") or t) > PENDING_FORGET_SECONDS:
                    r["pending"].pop(k, None)


def live_ring(mac):
    """Copie de l'état d'une bague (None si aucune TV ne l'a jamais signalée)."""
    mac = mac_upper(mac)
    with android_lock:
        r = android_rings.get(mac)
        if not r or not r["statusTs"]:
            return None
        out = json.loads(json.dumps(r, default=str))

    now_s = int(time.time())
    if out["online"] and now_s - int(out["statusTs"]) > GATEWAY_OFFLINE_AFTER:
        out["online"] = False
    out["now"] = now_s
    return out


def send_measure_cmd(mac, cmd):
    """
    Publie une mesure sur eis/colmi/<MAC>/cmd.
    Retourne {"ok": True, "reqId", "already"?} ou {"ok": False, "reason", "busy"?}.
    """
    mac = mac_upper(mac)
    t = int(time.time())

    with android_lock:
        r = android_rings.get(mac)

        if not r or not r["statusTs"]:
            return {"ok": False, "reason": "unknown"}
        if not r["online"] or t - int(r["statusTs"]) > GATEWAY_OFFLINE_AFTER:
            return {"ok": False, "reason": "gateway_offline"}
        if r["ring"] != "connected":
            return {"ok": False, "reason": "ring_disconnected"}

        running = [k for k in r["pending"] if k in ANDROID_MEASURES]
        if running and cmd not in running:
            return {"ok": False, "reason": "busy", "busy": running[0]}
        if cmd in running:
            return {"ok": True, "already": True, "reqId": r["pending"][cmd].get("reqId")}

        client = mqtt_client_ref
        if client is None or not client.is_connected():
            return {"ok": False, "reason": "mqtt_down"}

        req = "tg-" + uuid.uuid4().hex[:8]
        info = client.publish(
            f"{QRING_PREFIX}/{mac.replace(':', '')}/cmd",
            json.dumps({"cmd": cmd, "reqId": req}),
            qos=1,
        )
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            return {"ok": False, "reason": "mqtt_down"}

        r["pending"][cmd] = {"since": t, "requested": t, "reqId": req, "confirmed": False}
        r["errors"].pop(cmd, None)

    log.info("Mesure %s publiée pour %s (reqId %s)", cmd, mac, req)
    return {"ok": True, "reqId": req}


def get_ring_snapshot_db(ring_id):
    """Secours si aucune TV n'a encore signalé la bague : dernier état connu en base."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT s.online, s.battery, s.charging, s.heart_rate, s.spo2, s.hrv,
                       s.temperature, s.wear_status, s.ble_status,
                       s.last_measurement_at, s.updated_at,
                       g.name AS gateway, g.location AS gateway_location, g.last_seen AS gateway_seen
                FROM ring_current_state s
                LEFT JOIN gateways g ON g.id = s.gateway_id
                WHERE s.ring_id = %s
                """,
                (int(ring_id),),
            )
            row = cur.fetchone()
            return dict(row) if row else {}


# ---------------- Mise en forme ----------------

def hhmm(ts, seconds=False):
    if not ts:
        return "—"
    try:
        return datetime.fromtimestamp(int(ts)).strftime(
            "%H:%M:%S" if seconds else "%H:%M"
        )
    except Exception:
        return "—"


def day_hhmm(ts):
    if not ts:
        return "—"
    try:
        d = datetime.fromtimestamp(int(ts))
        if d.date() == datetime.now().date():
            return d.strftime("%H:%M")
        return d.strftime("%d/%m %H:%M")
    except Exception:
        return "—"


def ago_text(seconds):
    if seconds is None:
        return "—"
    s = max(0, int(seconds))
    if s < 60:
        return f"il y a {s} s"
    if s < 3600:
        return f"il y a {s // 60} min"
    if s < 86400:
        return f"il y a {s // 3600} h"
    return f"il y a {s // 86400} j"


def value_text(key, data):
    data = data or {}
    if key == "bp" or ("sbp" in data and "value" not in data):
        return f"{fmt_num(data.get('sbp'))}/{fmt_num(data.get('dbp'))} mmHg"
    if key == "all":
        parts = []
        for k, u in (("hr", "bpm"), ("spo2", "%"), ("temp", "°C")):
            if data.get(k) is not None:
                parts.append(f"{fmt_num(data[k])} {u}")
        return " · ".join(parts) or "—"
    unit = measure_info(key)[2]
    return f"{fmt_num(data.get('value'))} {unit}".strip()


def presence_text(ring):
    if not ring:
        return "⚪ État inconnu / Unknown state"
    if not ring.get("online"):
        return "⚫ TV hors ligne / TV offline"
    if ring.get("unbound") or ring.get("ring") == "unbound":
        return "⚪ Bague non associée à une TV / Ring not bound"
    if ring.get("ring") != "connected":
        return "🟡 HORS PORTÉE / OUT OF RANGE"
    if ring.get("worn") is False:
        return "🟠 BAGUE RETIRÉE / RING REMOVED"
    checked = ring.get("wornCheckedTs")
    if checked:
        return f"🟢 CONNECTÉE · PORTÉE / WORN (vérifiée à {hhmm(checked)})"
    return "🟢 CONNECTÉE · PORTÉE / CONNECTED · WORN"


def visible_measures(access):
    """Mesures affichées pour cet utilisateur (droit général ou mesures cochées)."""
    allowed = access.get("allowed_measures")
    return [k for k in TG_MEASURE_ORDER if not allowed or k in allowed]


def esc(value):
    return html_lib.escape(str(value if value is not None else ""), quote=False)


def fmt_fr(value):
    """36.6 -> 36,6 (affichage)."""
    return fmt_num(value).replace(".", ",")


def when_label(ts):
    """Aujourd'hui : 11:46 · hier : hier 21:03 · sinon : 24/09 18:40."""
    if not ts:
        return "—"
    try:
        d = datetime.fromtimestamp(int(ts))
    except Exception:
        return "—"
    today = datetime.now().date()
    if d.date() == today:
        return d.strftime("%H:%M")
    if d.date() == today - timedelta(days=1):
        return "hier · yday " + d.strftime("%H:%M")
    return d.strftime("%d/%m %H:%M")


def presence_parts(ring):
    """(emoji, français, english) — affichage bilingue de l'état."""
    if not ring:
        return "⚫", "Aucune TV ne signale cette bague", "No TV reports this ring"
    if not ring.get("online"):
        return "⚫", "TV hors ligne", "TV offline"
    if ring.get("unbound") or ring.get("ring") == "unbound":
        return "⚪", "Bague non associée", "Ring not paired"
    if ring.get("ring") != "connected":
        return "🟡", "Hors portée", "Out of range"
    if ring.get("worn") is False:
        return "🟠", "Bague retirée", "Ring removed"
    return "🟢", "Connectée · Portée", "Connected · Worn"


SCREEN_UNITS = {"hr": "bpm", "spo2": "%", "hrv": "ms", "temp": "°C"}
SCREEN_ICONS = {"hr": "❤️", "spo2": "🫁", "hrv": "💓", "temp": "🌡"}


def merged_latest(ring, latest):
    """Dernière valeur par mesure : la plus récente entre MQTT (en direct) et la base."""
    out = {}
    live = (ring or {}).get("values") or {}
    for key in TG_MEASURE_ORDER:
        candidates = [v for v in (live.get(key), (latest or {}).get(key)) if v and (v.get("data") or {}).get("value") is not None]
        if candidates:
            out[key] = max(candidates, key=lambda v: (int(v.get("ts") or 0), v.get("dur") is not None))
    return out


def summary_period(stamps):
    """Même jour : « 25/09/2026 12:26 » ; sinon « du 24/09 09:12 au 25/09 12:26 »."""
    stamps = sorted(int(t) for t in stamps if t)
    if not stamps:
        return ""
    first, last = datetime.fromtimestamp(stamps[0]), datetime.fromtimestamp(stamps[-1])
    if first.date() == last.date():
        return last.strftime("%d/%m/%Y %H:%M")
    return f"du {first.strftime('%d/%m %H:%M')} au {last.strftime('%d/%m %H:%M')}"


def format_ring_screen(access, ring, db_row=None, checking=False, latest=None, show_summary=True,
                       focus=None, exclude=None):
    """
    Écran d'une bague (HTML Telegram) :
      en-tête (nom, état, TV, batterie)
      [focus : mesure / vérification en cours ou son résultat — en haut]
      dernières mesures (sans la mesure du focus)
      [résumé — seulement sans focus]
      heure du statut TV
    """
    model = (ring or {}).get("model") or access.get("model")
    head = f"💍 <b>{esc(access['ring_name'])}</b>" + (f" · {esc(model)}" if model else "")
    lines = [head]

    if checking:
        lines.append("🔄 <b>Vérification du port…</b> | Checking wear…")
    else:
        emo, fr, en = presence_parts(ring)
        line = f"{emo} <b>{fr}</b> | {en}"
        if ring and ring.get("wornCheckedTs") and ring.get("worn") and ring.get("online") and ring.get("ring") == "connected":
            line += f" · ✓ {hhmm(ring['wornCheckedTs'])}"
        lines.append(line)

    if ring:
        tv = ring.get("deviceName") or ring.get("gateway") or "—"
        batt = ring.get("battery")
    else:
        row = db_row or {}
        tv = row.get("gateway_location") or row.get("gateway") or "—"
        batt = row.get("battery")
    batt_txt = f"🔋 {fmt_num(batt)} %" if batt is not None else "🔋 —"
    if (ring or {}).get("charging"):
        batt_txt += " ⚡"
    lines.append(f"📺 {esc(tv)} · {batt_txt}")

    if focus:
        lines.append("")
        lines.append(focus)
        show_summary = False

    vals = merged_latest(ring, latest)
    keys = visible_measures(access)
    status_ts2 = (ring or {}).get("statusTs")

    lines.append("")
    lines.append(f"📊 <b>latest health measurements recorded {hhmm(status_ts2, True)}</b>\n")
    shown = 0
    for key in keys:
        v = vals.get(key)
        #print(keys)
        if not v or key == exclude:
            continue
        shown += 1
        dur = v.get("dur")
        #lines.append("")
        lines.append(
            f"{SCREEN_ICONS[key]} {key.upper()}  : <b>{fmt_fr(v['data']['value'])} {SCREEN_UNITS[key]}</b>"
            f" · {when_label(v.get('ts'))} · ⏱ {f'{dur} s' if dur is not None else '—'}"
        )
    if not shown:
        lines.append("<i>Aucune autre mesure · No other readings</i>" if exclude else "<i>Aucune mesure · No readings yet</i>")
    elif show_summary:
        # Masqué pendant / après une mesure ou une vérification : le bloc de mesure prend sa place
        period = summary_period(vals[k].get("ts") for k in keys if k in vals)
        lines.append("")
        lines.append("✨ <b>Résumé · Summary</b>" + (f" — {period}" if period else ""))
        lines.append(" · ".join(
            f"{SCREEN_ICONS[k]} {fmt_fr(vals[k]['data']['value'])} {SCREEN_UNITS[k]}"
            for k in keys if k in vals
        ))

    status_ts = (ring or {}).get("statusTs")
    if status_ts:
        lines.append("\n")
        #lines.append(f"🕒 Statut TV · TV status {hhmm(status_ts, True)}")

    return "\n".join(lines)


# Dernières valeurs en base (après un redémarrage du bot, avant toute nouvelle mesure)
_latest_cache = {}
LATEST_CACHE_SECONDS = 60
LATEST_DB_METRICS = {"heart_rate": "hr", "spo2": "spo2", "hrv": "hrv", "temperature": "temp"}


def get_latest_values_db(ring_id):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT k.metric, m.time, m.value, m.extra
                FROM unnest(%s::text[]) AS k(metric)
                CROSS JOIN LATERAL (
                    SELECT time, value, extra
                    FROM ring_measurements
                    WHERE ring_id = %s AND metric = k.metric
                      AND status = 'ok' AND value IS NOT NULL
                    ORDER BY time DESC
                    LIMIT 1
                ) m
                """,
                (list(LATEST_DB_METRICS), int(ring_id)),
            )
            out = {}
            for r in cur.fetchall():
                extra = r.get("extra") or {}
                out[LATEST_DB_METRICS[r["metric"]]] = {
                    "ts": int(r["time"].timestamp()),
                    "data": {"value": r["value"]},
                    "dur": extra.get("duration_s"),
                }
            return out


async def latest_values(ring_id):
    hit = _latest_cache.get(ring_id)
    if hit and time.time() - hit[0] < LATEST_CACHE_SECONDS:
        return hit[1]
    try:
        data = await asyncio.to_thread(get_latest_values_db, ring_id)
    except Exception:
        log.exception("Dernières valeurs en base illisibles")
        data = (hit or (0, {}))[1]
    _latest_cache[ring_id] = (time.time(), data)
    return data


def _result_times(tr, result):
    started = (result or {}).get("started") or tr.get("started") or tr["t0"]
    end = (result or {}).get("ts") or int(time.time())
    dur = (result or {}).get("dur")
    if dur is None:
        dur = max(0, int(end) - int(started))
    return started, end, dur


def progress_bar(value, total, width=10):
    total = max(1, int(total or 1))
    n = max(0, min(width, round(width * (value or 0) / total)))
    return "▰" * n + "▱" * (width - n)


def error_parts(phase):
    """ERROR_TEXT « 🖐 Français / English » -> (emoji, français, english)."""
    txt = ERROR_TEXT.get(phase, f"❌ {phase}")
    fr_txt, _, en_txt = txt.partition(" / ")
    emo, _, fr_rest = fr_txt.partition(" ")
    return emo, fr_rest, en_txt


def short_label(key):
    return measure_info(key)[0]


def prev_line(tr, failed=False):
    p = tr.get("prev")
    if not p:
        return None
    unit = SCREEN_UNITS.get(tr["cmd"], measure_info(tr["cmd"])[2])
    head = "Dernière valeur · Last value" if failed else "Précédente · Previous"
    return f"↩️ {head} : {fmt_fr(p['v'])} {unit} · {when_label(p.get('ts'))}"


def format_measure_block(tr, phase, elapsed=None, result=None):
    """Bloc affiché EN HAUT de l'écran pendant / après une mesure (ou une vérification du port)."""
    if tr.get("mode") == "wear":
        return format_wear_block(tr, phase, elapsed, result)

    key = tr["cmd"]
    label = short_label(key)
    limit = measure_info(key)[3]
    lines = []

    if phase in ("requested", "measuring"):
        status = "demande envoyée · request sent" if phase == "requested" else "mesure en cours · measuring"
        el = int(elapsed or 0) if phase == "measuring" else max(0, int(time.time()) - int(tr["t0"]))
        lines.append(f"<b>{label} — {status}</b>")
        lines.append(f"{progress_bar(el, limit)}  {el} s / {limit} s")
        lines.append(f"🕒 Début · Start {hhmm(tr.get('started') or tr['t0'], True)}")
        if tr.get("shared"):
            lines.append("👥 Mesure déjà lancée, résultat partagé · Shared measurement")
        pl = prev_line(tr)
        if pl:
            lines.append(pl)
    elif (result or {}).get("refused"):
        # Refus immédiat (TV hors ligne, hors portée…) : pas de durée
        emo, fr_txt, en_txt = error_parts(phase)
        lines.append(f"<b>{emo} {label} : {fr_txt}</b>")
        if en_txt:
            lines.append(en_txt)
        lines.append(f"🕒 {hhmm(result.get('ts') or tr['t0'], True)}")
    else:
        started, end, dur = _result_times(tr, result)
        if phase == "ok":
            lines.append(f"<b>✅ {label} : {value_text(key, result.get('data')).replace('.', ',')}</b>")
        else:
            emo, fr_txt, en_txt = error_parts(phase)
            lines.append(f"<b>{emo} {label} : {fr_txt}</b>")
            if en_txt:
                lines.append(en_txt)
        lines.append(f"🕒 {hhmm(started, True)} → {hhmm(end, True)} · ⏱ {dur} s")
        pl = prev_line(tr, failed=phase != "ok")
        if pl:
            lines.append(pl)

    return "\n".join(lines)


def format_wear_block(tr, phase, elapsed=None, result=None):
    """
    État / Status : une mesure sert de test de port.
    Pas de problème pendant WEAR_CHECK_SECONDS => « portée », même si la mesure continue
    (elle s'affiche en dessous jusqu'au résultat). Si la TV signale ensuite « retirée »,
    l'affichage se corrige.
    """
    key = tr["cmd"]
    limit = measure_info(key)[3]
    worn_at = tr.get("worn_ok")
    worn_line = f"<b>🟢 Bague portée — vérifiée à {hhmm(worn_at, True)}</b> | Ring worn" if worn_at else None
    lines = []

    if phase == "requested":
        lines.append("<b>🔄 Check status de la bague · Wear check</b>")
        lines.append(f"{progress_bar(0, WEAR_CHECK_SECONDS)}  ⏳ demande envoyée · request sent")
    elif phase == "measuring" and not worn_at:
        el = int(elapsed or 0)
        lines.append("<b>🔄 Check status de la bague · Wear check</b>")
        lines.append(f"{progress_bar(el, WEAR_CHECK_SECONDS)}  {el} s / {WEAR_CHECK_SECONDS} s")
    elif phase in ("measuring", "worn"):
        lines.append(worn_line)
        if phase == "measuring" and tr.get("show_value"):
            el = int(elapsed or 0)
            lines.append(f"{short_label(key)} — mesure en cours · measuring")
            lines.append(f"{progress_bar(el, limit)}  {el} s / {limit} s")
    elif phase == "ok":
        at = worn_at or (result or {}).get("ts") or int(time.time())
        lines.append(f"<b>🟢 Bague portée — vérifiée à {hhmm(at, True)}</b> | Ring worn")
        if tr.get("show_value"):
            started, end, dur = _result_times(tr, result)
            lines.append(
                f"✅ {short_label(key)} : <b>{value_text(key, (result or {}).get('data')).replace('.', ',')}</b>"
                f" · 🕒 {hhmm(started, True)} → {hhmm(end, True)} · ⏱ {dur} s"
            )
    elif phase in ("ring_removed", "ring_disconnected", "gateway_offline", "unknown", "mqtt_down"):
        # Problème signalé (même après un « portée » provisoire) : l'affichage se corrige
        emo, fr_txt, en_txt = error_parts(phase)
        lines.append(f"<b>{emo} {fr_txt}</b>")
        if en_txt:
            lines.append(en_txt)
        lines.append(f"🕒 {hhmm((result or {}).get('ts') or int(time.time()), True)}")
    elif worn_at:
        # Port vérifié, mais la mesure elle-même n'a pas abouti (pas de résultat, échec…)
        lines.append(worn_line)
        if tr.get("show_value"):
            emo, fr_txt, _ = error_parts(phase)
            lines.append(f"{short_label(key)} : {emo} {fr_txt}")
    elif phase == "timeout":
        lines.append("<b>❓ Pas de signal — port non confirmé</b>")
        lines.append("Wear not confirmed — vérifie la bague au doigt puis réessaie · check the ring and retry")
    else:
        emo, fr_txt, en_txt = error_parts(phase)
        lines.append("<b>⚠️ Vérification du status de la bague impossible</b>")
        lines.append(f"Wear check failed · {emo} {fr_txt}")

    return "\n".join(lines)


def ring_keyboard(access):
    rid = access["ring_id"]
    rows = []

    top = [InlineKeyboardButton("🔄 État / Status", callback_data=f"st:{rid}")]
    if access.get("can_view_history"):
        top.append(InlineKeyboardButton("📊 Historique", callback_data=f"history:{rid}"))
    rows.append(top)

    measures = [
        InlineKeyboardButton(TG_MEASURES[k][0], callback_data=f"ms:{rid}:{k}")
        for k in TG_MEASURE_ORDER
        if measure_allowed(access, k)
    ]
    for i in range(0, len(measures), 2):
        rows.append(measures[i:i + 2])

    last = [InlineKeyboardButton("ℹ️ Infos", callback_data=f"inf:{rid}")]

    # Mini App Telegram (QRing Admin /webapp/ring/<mac>) : l'autorisation réelle est
    # vérifiée côté serveur avec initData signé. Visible si TELEGRAM_WEBAPP_BASE_URL est rempli.
    if TELEGRAM_WEBAPP_BASE_URL and access.get("can_view"):
        mac_key = str(access.get("mac") or "").replace(":", "").replace("-", "").lower()
        if len(mac_key) == 12:
            last.append(
                InlineKeyboardButton(
                    "🌐 Web App",
                    web_app=WebAppInfo(url=f"{TELEGRAM_WEBAPP_BASE_URL}/webapp/ring/{mac_key}"),
                )
            )
    rows.append(last)

    rows.append([InlineKeyboardButton("⬅️ Mes bagues / My rings", callback_data="rings")])
    return InlineKeyboardMarkup(rows)


async def safe_edit(bot, chat_id, message_id, text, markup):
    """Modifie un message ; ignore « message is not modified » et les limites de débit."""
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text[:4096],
            reply_markup=markup,
            parse_mode="HTML",
        )
        return True
    except BadRequest as exc:
        if "not modified" in str(exc).lower():
            return True
        log.warning("Edition message impossible : %s", exc)
        return False
    except RetryAfter as exc:
        log.warning("Telegram limite le débit (%s s)", exc.retry_after)
        return False
    except Forbidden:
        return False


async def show_ring_screen(bot, chat_id, message_id, access, extra_block=None, checking=False, exclude=None):
    ring = live_ring(access["mac"])
    db_row = None
    if not ring:
        try:
            db_row = await asyncio.to_thread(get_ring_snapshot_db, access["ring_id"])
        except Exception:
            log.exception("Etat DB impossible")
    latest = await latest_values(access["ring_id"])
    text = format_ring_screen(access, ring, db_row, checking=checking, latest=latest,
                              show_summary=not extra_block and not checking,
                              focus=extra_block, exclude=exclude)
    ok_ = await safe_edit(bot, chat_id, message_id, text, ring_keyboard(access))
    if ok_:
        watch_ring_message(chat_id, message_id, access, extra_block, ring, exclude)
    return ok_


# ---------------- Écran de bague mis à jour tout seul ----------------
# chat_id -> écran surveillé (un seul par conversation : le dernier affiché).
# Quand l'état de la bague change (TV, Bluetooth, port, batterie, nouvelle
# valeur), le message est réécrit sans action de l'utilisateur.

ring_watchers = {}


def ring_signature(ring):
    if not ring:
        return None
    vals = ring.get("values") or {}
    return (
        bool(ring.get("online")), ring.get("ring"), ring.get("worn"), bool(ring.get("unbound")),
        ring.get("wornCheckedTs"), ring.get("battery"), bool(ring.get("charging")),
        ring.get("deviceName") or ring.get("gateway"),
        tuple(sorted((k, v.get("ts")) for k, v in vals.items())),
    )


def watch_ring_message(chat_id, message_id, access, block=None, ring=None, exclude=None):
    ring_watchers[chat_id] = {
        "message_id": message_id,
        "ring_id": int(access["ring_id"]),
        "mac": mac_upper(access["mac"]),
        "user_id": None,
        "block": block,
        "exclude": exclude,
        "sig": ring_signature(ring if ring is not None else live_ring(access["mac"])),
        "until": time.time() + RING_WATCH_MINUTES * 60,
        "last_edit": time.time(),
        "access": access,
    }


def unwatch_ring_message(chat_id, message_id=None):
    w = ring_watchers.get(chat_id)
    if w and (message_id is None or w["message_id"] == message_id):
        ring_watchers.pop(chat_id, None)


async def watch_tick(bot):
    now_s = time.time()

    for chat_id, w in list(ring_watchers.items()):
        if now_s > w["until"]:
            ring_watchers.pop(chat_id, None)
            continue

        # Une mesure suivie dans ce message s'occupe déjà de l'affichage
        if (chat_id, w["message_id"]) in measure_trackers:
            continue

        ring = live_ring(w["mac"])
        sig = ring_signature(ring)
        if sig == w["sig"] or now_s - w["last_edit"] < RING_WATCH_MIN_EDIT_SECONDS:
            continue

        # Droits relus à chaque changement : une affectation retirée coupe l'affichage
        try:
            access = await asyncio.to_thread(get_ring_access, chat_id, w["ring_id"])
        except Exception:
            log.exception("Droits illisibles (écran surveillé)")
            continue

        if not access:
            ring_watchers.pop(chat_id, None)
            await safe_edit(bot, chat_id, w["message_id"], "⛔ Accès retiré / Access removed.", None)
            continue

        text = format_ring_screen(access, ring, latest=await latest_values(w["ring_id"]),
                                  show_summary=not w.get("block"),
                                  focus=w.get("block"), exclude=w.get("exclude"))

        w["sig"] = sig
        w["last_edit"] = now_s
        if not await safe_edit(bot, chat_id, w["message_id"], text, ring_keyboard(access)):
            # Message supprimé ou trop ancien : on arrête de le suivre
            ring_watchers.pop(chat_id, None)


# ---------------- Suivi des mesures ----------------

def save_measure_trackers():
    try:
        MEASURE_TRACKERS_FILE.write_text(
            json.dumps(
                [dict(v, chat_id=k[0], message_id=k[1]) for k, v in measure_trackers.items()],
                default=str,
            ),
            encoding="utf-8",
        )
    except Exception:
        log.exception("Sauvegarde des mesures en cours impossible")


def drop_tracker(chat_id, message_id):
    if measure_trackers.pop((chat_id, message_id), None) is not None:
        save_measure_trackers()


def measure_outcome(tr, ring):
    """
    Retourne (phase, elapsed, result) :
      phase = requested | measuring | ok | worn | <code erreur>
    """
    key = tr["cmd"]
    now_s = time.time()
    phase, elapsed, result = None, None, None

    if ring:
        values = ring.get("values") or {}
        errors = ring.get("errors") or {}
        pending = (ring.get("pending") or {}).get(key)

        def matches(x):
            # même reqId ; sinon (reqId inconnu d'un côté) résultat arrivé après la demande
            if not x:
                return False
            if tr.get("reqId") and x.get("reqId"):
                return x["reqId"] == tr["reqId"]
            return (x.get("ts") or 0) >= tr["t0"] - 1

        v = values.get(key)
        e = errors.get(key)
        if matches(v):
            phase, result = "ok", v
        elif matches(e):
            phase, result = (e.get("code") or "measure_failed"), e
        elif not ring.get("online"):
            phase = "gateway_offline"
        elif ring.get("ring") != "connected":
            phase = "ring_disconnected"
        elif pending and (not tr.get("reqId") or pending.get("reqId") in (None, tr["reqId"])):
            if pending.get("confirmed"):
                tr["started"] = pending.get("since")
                phase = "measuring"
                elapsed = max(0, int(ring.get("now", now_s)) - int(pending.get("since") or tr["t0"]))
            else:
                phase = "requested"
        elif now_s - tr["t0"] > 15:
            # Plus rien en attente et aucun résultat pour cette demande
            phase = "timeout"
    else:
        phase = "unknown"

    if phase is None:
        phase = "measuring" if tr.get("started") else "requested"
        if tr.get("started"):
            elapsed = int(now_s - tr["started"])

    if phase in ("requested", "measuring"):
        if now_s - tr["t0"] > measure_info(key)[3] + MEASURE_MARGIN_SECONDS:
            phase, elapsed = "timeout", None

    # État / Status : WEAR_CHECK_SECONDS de mesure sans problème => bague portée
    # (la mesure continue ; un « retirée » signalé plus tard corrige l'affichage)
    if tr.get("mode") == "wear" and phase == "measuring" and not tr.get("worn_ok") \
            and (elapsed or 0) >= WEAR_CHECK_SECONDS:
        tr["worn_ok"] = int(now_s)
        mark_worn_verified(tr["mac"])
        if not tr.get("show_value"):
            return "worn", None, None

    return phase, elapsed, result


async def measure_loop(bot):
    """Toutes les MEASURE_TICK_SECONDS : barre de progression, résultats, écrans surveillés."""
    ctx = type("Ctx", (), {"bot": bot})()
    log.info("Suivi des mesures actif (toutes les %.0f s)", MEASURE_TICK_SECONDS)
    while True:
        try:
            await measure_tick(ctx)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Suivi des mesures : erreur (on continue)")
        await asyncio.sleep(MEASURE_TICK_SECONDS)


async def measure_tick(context: ContextTypes.DEFAULT_TYPE):
    forget_stale_pending()

    await watch_tick(context.bot)

    try:
        await alert_tick(context.bot)
    except Exception:
        log.exception("Alertes : erreur (on continue)")

    if not measure_trackers:
        return

    bot = context.bot
    rings_seen = {}
    changed = False

    for key, tr in list(measure_trackers.items()):
        chat_id, message_id = key
        mac = tr["mac"]

        if mac not in rings_seen:
            rings_seen[mac] = live_ring(mac)
        ring = rings_seen[mac]

        was_flag = tr.get("worn_ok")
        phase, elapsed, result = measure_outcome(tr, ring)
        final = phase not in ("requested", "measuring")
        now_s = time.time()

        if not final and tr.get("worn_ok") == was_flag:
            if phase == tr.get("phase") and now_s - tr.get("last_edit", 0) < MEASURE_EDIT_EVERY_SECONDS:
                continue

        try:
            access = await asyncio.to_thread(get_ring_access, tr["user_id"], tr["ring_id"])
        except Exception:
            log.exception("Droits de la bague illisibles")
            continue

        if not access:
            # Affectation retirée pendant la mesure
            measure_trackers.pop(key, None)
            changed = True
            await safe_edit(bot, chat_id, message_id, "⛔ Accès retiré / Access removed.", None)
            continue

        if ring:
            ring = live_ring(mac) or ring
        checking = tr.get("mode") == "wear" and not final and not tr.get("worn_ok")
        block = format_measure_block(tr, phase, elapsed, result)
        latest = await latest_values(tr["ring_id"])
        exclude = tr["cmd"] if (tr.get("mode") != "wear" or tr.get("show_value")) else None
        text = format_ring_screen(access, ring, checking=checking, latest=latest,
                                  show_summary=False, focus=block, exclude=exclude)
        await safe_edit(bot, chat_id, message_id, text, ring_keyboard(access))

        tr["phase"] = phase
        tr["last_edit"] = now_s
        changed = True

        if final:
            measure_trackers.pop(key, None)
            # Le message reste à jour tout seul, avec le résultat en bas
            watch_ring_message(chat_id, message_id, access, block, ring, exclude)

    if changed:
        save_measure_trackers()


def refused_block(key, reason, mode=None):
    t0 = int(time.time())
    phase = reason if reason in ERROR_TEXT else "measure_failed"
    tr = {"cmd": key, "t0": t0, "mode": mode}
    if mode == "wear":
        return format_wear_block(tr, phase, result={"ts": t0})
    return format_measure_block(tr, phase, result={"ts": t0, "refused": True})


async def start_measure(update, context, ring_id, key):
    q = update.callback_query
    user = update.effective_user
    chat_id = q.message.chat_id
    message_id = q.message.message_id

    access = await asyncio.to_thread(get_ring_access, user.id, ring_id)
    if not access:
        await q.answer("⛔ Accès refusé / Access denied.", show_alert=True)
        return

    if key not in TG_MEASURES or not measure_allowed(access, key):
        await q.answer("⛔ Mesure non autorisée / Measurement not allowed.", show_alert=True)
        return

    existing = measure_trackers.get((chat_id, message_id))
    if existing:
        await q.answer(
            f"🟠 {measure_info(existing['cmd'])[0]} déjà en cours — attends le résultat.",
            show_alert=True,
        )
        return

    # Valeur précédente de cette mesure (affichée pour comparer)
    before = merged_latest(live_ring(access["mac"]), await latest_values(access["ring_id"])).get(key)

    res = send_measure_cmd(access["mac"], key)

    if not res.get("ok") and res.get("reason") == "busy":
        busy = measure_info(res["busy"])[0]
        await q.answer(
            f"🟠 Mesure {busy} en cours sur cette bague — réessaie à la fin.\n"
            "Another measurement is running — try again when it ends.",
            show_alert=True,
        )
        return

    if not res.get("ok"):
        # Refus immédiat : TV hors ligne, bague hors portée, inconnue, broker injoignable
        await q.answer()
        await show_ring_screen(context.bot, chat_id, message_id, access, refused_block(key, res.get("reason")))
        return

    await q.answer(
        "👥 Mesure déjà en cours — résultat partagé" if res.get("already") else "▶️ Mesure lancée / Started"
    )

    tr = {
        "ring_id": int(ring_id),
        "mac": mac_upper(access["mac"]),
        "cmd": key,
        "reqId": res.get("reqId"),
        "t0": int(time.time()),
        "user_id": int(user.id),
        "shared": bool(res.get("already")),
        "phase": "requested",
        "last_edit": time.time(),
        "prev": {"v": before["data"]["value"], "ts": before.get("ts")} if before else None,
    }
    measure_trackers[(chat_id, message_id)] = tr
    save_measure_trackers()

    await show_ring_screen(
        context.bot, chat_id, message_id, access, format_measure_block(tr, "requested"), exclude=key
    )


async def start_wear_check(update, context, ring_id):
    """
    Bouton « État » : actualise l'écran et vérifie que la bague est portée.
      - TV hors ligne / hors portée : affiché tout de suite, rien n'est lancé
      - port vérifié il y a moins de WEAR_REUSE_SECONDS : réutilisé
      - une mesure tourne déjà : on la suit (elle sert de test de port)
      - sinon : une mesure HR est lancée ; PORTÉE seulement si une vraie valeur arrive,
        PORTÉE après WEAR_CHECK_SECONDS sans problème (la mesure continue en dessous)
    """
    q = update.callback_query
    user = update.effective_user
    chat_id = q.message.chat_id
    message_id = q.message.message_id

    access = await asyncio.to_thread(get_ring_access, user.id, ring_id)
    if not access:
        await q.answer("⛔ Accès refusé / Access denied.", show_alert=True)
        return

    tr = measure_trackers.get((chat_id, message_id))
    if tr:
        # Une mesure / vérification est déjà suivie dans ce message : on la réaffiche
        await q.answer("🔄")
        tr["last_edit"] = 0
        tr["phase"] = None
        return

    ring = live_ring(access["mac"])
    now_s = int(time.time())

    if (
        not ring
        or not ring.get("online")
        or ring.get("unbound")
        or ring.get("ring") != "connected"
    ):
        await q.answer("🔄")
        await show_ring_screen(context.bot, chat_id, message_id, access)
        return

    checked = ring.get("wornCheckedTs")
    if ring.get("worn") and checked and now_s - int(checked) <= WEAR_REUSE_SECONDS:
        await q.answer("🟢 Port vérifié récemment / Recently checked")
        await show_ring_screen(context.bot, chat_id, message_id, access)
        return

    running = [k for k in (ring.get("pending") or {}) if k in ANDROID_MEASURES]
    if running:
        key = running[0]
        req = ring["pending"][key].get("reqId")
        shared = True
    else:
        res = send_measure_cmd(access["mac"], "hr")
        if not res.get("ok"):
            if res.get("reason") == "busy":
                key, req, shared = res["busy"], None, True
            else:
                await q.answer()
                await show_ring_screen(
                    context.bot, chat_id, message_id, access, refused_block("hr", res.get("reason"), "wear")
                )
                return
        else:
            key, req, shared = "hr", res.get("reqId"), bool(res.get("already"))

    await q.answer("🔄 Vérification du port… / Checking…")

    tr = {
        "ring_id": int(ring_id),
        "mac": mac_upper(access["mac"]),
        "cmd": key,
        "reqId": req,
        "t0": now_s,
        "user_id": int(user.id),
        "shared": shared,
        "mode": "wear",
        "show_value": measure_allowed(access, key),
        "phase": "requested",
        "last_edit": time.time(),
    }
    measure_trackers[(chat_id, message_id)] = tr
    save_measure_trackers()

    await show_ring_screen(
        context.bot, chat_id, message_id, access, format_wear_block(tr, "requested"), checking=True
    )


async def recover_measure_trackers(bot):
    """Au démarrage : les mesures suivies avant un redémarrage ne sont plus suivies."""
    try:
        if not MEASURE_TRACKERS_FILE.exists():
            return
        items = json.loads(MEASURE_TRACKERS_FILE.read_text(encoding="utf-8") or "[]")
    except Exception:
        log.exception("Lecture des mesures interrompues impossible")
        return

    for tr in items:
        try:
            label = measure_info(tr.get("cmd") or "")[1]
            if tr.get("mode") == "wear":
                label = "🔄 Vérification du port / Wear check"
            await safe_edit(
                bot,
                int(tr["chat_id"]),
                int(tr["message_id"]),
                f"💍 Mesure interrompue / Measurement interrupted\n\n{label}\n"
                f"🕒 {hhmm(tr.get('t0'), True)}\n"
                "Le bot a redémarré pendant la mesure. Relance-la depuis la bague.\n"
                "The bot restarted during the measurement.",
                InlineKeyboardMarkup([[InlineKeyboardButton(
                    "💍 Ouvrir la bague / Open ring", callback_data=f"ring:{tr['ring_id']}"
                )]]),
            )
        except Exception:
            log.exception("Message de mesure interrompue impossible")

    measure_trackers.clear()
    save_measure_trackers()


# ---------------- Alertes (notifications Telegram) ----------------
# Le bot surveille l'état des bagues reçu de Mosquitto et prévient les utilisateurs affectés
# qui ont le droit « Alertes » (+ TELEGRAM_ADMIN_IDS). Une alerte par type et par bague ;
# au retour à la normale, le message d'alerte est modifié (« ✅ Rétablie … »), pas de nouveau message.
#   ⚫ TV hors ligne / 🟡 hors portée : confirmées après ALERT_CONFIRM_SECONDS (anti-coupures brèves)
#   🖐 bague retirée : dès qu'une mesure la détecte ; levée à la prochaine mesure réussie
#   🪫 batterie faible : notification silencieuse ; levée en charge ou au-dessus du seuil + 5 %

ALERTS_ENABLED = os.getenv("TELEGRAM_ALERTS_ENABLED", "1").strip().strip(",;").strip().lower() not in ("0", "false", "no", "off")
ALERT_CONFIRM_SECONDS = max(10, env_int("TELEGRAM_ALERT_CONFIRM_SECONDS", "60"))
ALERT_BATTERY_LOW = env_int("TELEGRAM_ALERT_BATTERY_LOW", "20")
ALERT_STARTUP_GRACE = 20          # messages conservés reçus au démarrage : pas d'alerte
ALERTS_FILE = BASE_DIR / "telegram_alerts.json"

BOT_STARTED_AT = time.time()
active_alerts = {}                # "MAC|type" -> {since, sent, msgs:[[chat, msg]], ring_id, name, tv}
_alert_pending = {}               # "MAC|type" -> première détection (confirmation)
_alert_ring_cache = {}            # MAC -> (t, ring_id, name, [chat_ids])

ALERT_INFO = {
    # type: (emoji, français, english, conseil fr · en, silencieuse)
    "offline": ("⚫", "TV hors ligne", "TV offline", "Vérifier que la TV est allumée et connectée · Check the TV is on and online", False),
    "out_of_range": ("🟡", "Hors portée", "Out of range", "La bague est trop loin de la TV · The ring is too far from the TV", False),
    "removed": ("🖐", "Bague retirée", "Ring removed", "Veuillez porter la bague · Please wear the ring", False),
    "battery": ("🪫", "Batterie faible", "Low battery", "Mettre la bague en charge · Please charge the ring", True),
}
ALERT_BACK = {
    "offline": "TV de nouveau en ligne · TV back online",
    "out_of_range": "Bague de nouveau à portée · Ring back in range",
    "removed": "Bague de nouveau portée (mesure réussie) · Ring worn again",
    "battery": "Batterie OK · Battery OK",
}


def load_alerts():
    try:
        if ALERTS_FILE.exists():
            active_alerts.update(json.loads(ALERTS_FILE.read_text(encoding="utf-8") or "{}"))
    except Exception:
        log.exception("Lecture des alertes impossible")


def save_alerts():
    try:
        ALERTS_FILE.write_text(json.dumps(active_alerts), encoding="utf-8")
    except Exception:
        log.exception("Sauvegarde des alertes impossible")


def alert_conditions(r, now_s):
    """Conditions en cours pour une bague (état MQTT) -> {type: détail}."""
    cond = {}
    if r.get("unbound") or not r.get("statusTs"):
        return cond
    online = r.get("online") and now_s - int(r["statusTs"]) <= GATEWAY_OFFLINE_AFTER
    if not online:
        cond["offline"] = None
        return cond                      # TV hors ligne : l'état de la bague n'est plus connu
    if r.get("ring") == "disconnected":
        cond["out_of_range"] = None
    elif r.get("ring") == "connected":
        if r.get("worn") is False:
            cond["removed"] = None
        batt = r.get("battery")
        if batt is not None and not r.get("charging"):
            key_on = f"{r['mac']}|battery" in active_alerts
            limit = ALERT_BATTERY_LOW + (5 if key_on else 0)   # hystérésis
            if int(batt) < limit:
                cond["battery"] = int(batt)
    return cond


def get_alert_ring(mac):
    hit = _alert_ring_cache.get(mac)
    if hit and time.time() - hit[0] < 60:
        return hit[1:]
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name FROM rings WHERE mac = %s::macaddr AND active = TRUE", (mac,))
            row = cur.fetchone()
    if not row:
        data = (None, None, [])
    else:
        data = (row["id"], row["name"], get_alert_chat_ids(row["id"]))
    _alert_ring_cache[mac] = (time.time(),) + data
    return data


def alert_text(kind, name, tv, since, detail=None):
    emo, fr, en, advice, _ = ALERT_INFO[kind]
    title = f"{fr} {detail} %" if kind == "battery" and detail is not None else fr
    return (
        f"{emo} <b>{esc(name)} — {title}</b> | {en}\n"
        f"{advice}\n"
        f"🕒 {when_label(since)}" + (f" · 📺 {esc(tv)}" if tv else "")
    )


def alert_back_text(kind, name, since, end):
    emo, fr, _, _, _ = ALERT_INFO[kind]
    mins = max(1, round((end - since) / 60))
    return (
        f"✅ <b>{esc(name)} — Rétablie</b> | Back to normal\n"
        f"{ALERT_BACK[kind]}\n"
        f"{emo} {fr} de {hhmm(since)} à {hhmm(end)} · ⏱ {mins} min"
    )


def alert_markup(ring_id):
    return InlineKeyboardMarkup([[InlineKeyboardButton("💍 Ouvrir la bague / Open ring", callback_data=f"ring:{ring_id}")]])


async def alert_tick(bot):
    if not ALERTS_ENABLED:
        return
    now_s = time.time()
    with android_lock:
        snapshot = {mac: dict(r) for mac, r in android_rings.items()}

    current = {}
    for mac, r in snapshot.items():
        for kind, detail in alert_conditions(r, now_s).items():
            current[f"{mac}|{kind}"] = (mac, kind, detail, r)

    changed = False

    # 1) nouvelles conditions (après confirmation)
    for key, (mac, kind, detail, r) in current.items():
        if key in active_alerts:
            continue
        first = _alert_pending.setdefault(key, now_s)
        if kind in ("offline", "out_of_range") and now_s - first < ALERT_CONFIRM_SECONDS:
            continue
        if first < BOT_STARTED_AT + ALERT_STARTUP_GRACE:
            # déjà présent au démarrage du bot : on le note sans prévenir (pas de rafale au redémarrage)
            active_alerts[key] = {"since": int(first), "sent": False, "msgs": [], "silent_start": True}
            changed = True
            continue
        try:
            ring_id, name, chats = await asyncio.to_thread(get_alert_ring, mac)
        except Exception:
            log.exception("Destinataires d'alerte illisibles")
            continue
        entry = {"since": int(first), "sent": False, "msgs": [], "ring_id": ring_id, "name": name,
                 "tv": r.get("deviceName") or r.get("gateway")}
        active_alerts[key] = entry
        changed = True
        if not ring_id or not chats:
            continue
        text = alert_text(kind, name, entry["tv"], entry["since"], detail)
        for chat in chats:
            try:
                m = await bot.send_message(
                    chat_id=chat, text=text, parse_mode="HTML", reply_markup=alert_markup(ring_id),
                    disable_notification=ALERT_INFO[kind][4],
                )
                entry["msgs"].append([chat, m.message_id])
            except (Forbidden, BadRequest) as exc:
                log.info("Alerte non délivrée à %s : %s", chat, exc)
            except RetryAfter as exc:
                await asyncio.sleep(exc.retry_after)
            except Exception:
                log.exception("Envoi d'alerte")
        entry["sent"] = bool(entry["msgs"])
        log.info("Alerte %s %s envoyée à %d destinataire(s)", kind, mac, len(entry["msgs"]))

    # 2) conditions disparues : « ✅ Rétablie » dans le même message
    for key in [k for k in active_alerts if k not in current]:
        entry = active_alerts.pop(key)
        _alert_pending.pop(key, None)
        changed = True
        kind = key.split("|", 1)[1]
        if not entry.get("sent") or kind not in ALERT_INFO:
            continue
        text = alert_back_text(kind, entry.get("name") or key.split("|")[0], entry["since"], int(now_s))
        for chat, msg in entry.get("msgs", []):
            await safe_edit(bot, chat, msg, text, alert_markup(entry["ring_id"]) if entry.get("ring_id") else None)

    # une condition détectée mais disparue avant confirmation : on oublie
    for key in [k for k in _alert_pending if k not in current]:
        _alert_pending.pop(key, None)

    if changed:
        save_alerts()


# ---------------- Infos ----------------

def format_ring_info(access, ring):
    lines = [f"ℹ️ {access['ring_name']}", ""]
    lines.append(f"📡 MAC : {access['mac']}")
    lines.append(f"🏷 Modèle / Model : {(ring or {}).get('model') or access.get('model') or '—'}")
    if ring:
        lines.append(f"🧩 Firmware : {ring.get('firmware') or '—'}")
        lines.append("")
        lines.append(presence_text(ring))
        lines.append(f"📺 TV : {ring.get('deviceName') or ring.get('gateway') or '—'}")
        lines.append(f"📶 TV : {'en ligne / online' if ring.get('online') else 'hors ligne / offline'}")
        ble = {"connected": "connectée", "disconnected": "déconnectée", "connecting": "connexion…",
               "unbound": "non associée"}.get(ring.get("ring"), ring.get("ring") or "—")
        lines.append(f"🔗 Bluetooth : {ble}")
        worn = ring.get("worn")
        lines.append(f"🖐 Port : {'portée / worn' if worn else 'retirée / removed' if worn is False else '—'}")
        batt = ring.get("battery")
        lines.append(
            f"🔋 Batterie : {fmt_num(batt) + ' %' if batt is not None else '—'}"
            + (" · ⚡ en charge" if ring.get("charging") else "")
        )
        if ring.get("statusTs"):
            lines.append(f"🕒 Dernier statut : {hhmm(ring['statusTs'], True)} ({ago_text(ring.get('now', time.time()) - int(ring['statusTs']))})")
    else:
        lines.append("")
        lines.append("⚫ Aucune TV ne signale cette bague pour le moment.")

    lines.append("")
    rights = []
    if access.get("can_view_history"):
        rights.append("historique")
    if access.get("can_live"):
        allowed = access.get("allowed_measures")
        rights.append("mesures : " + ("toutes" if not allowed else ", ".join(
            TG_MEASURES[k][0] for k in TG_MEASURE_ORDER if k in allowed) or "aucune"))
    if access.get("can_receive_alerts"):
        rights.append("alertes")
    lines.append("🔐 Tes droits / Your rights : " + (" · ".join(rights) or "consultation"))
    return "\n".join(lines)


# ---------------- Historique (valeurs en base, pages de 20) ----------------

HISTORY_PAGE_SIZE = 20

# métrique PostgreSQL -> (libellé, unité, clé de droit ; None = droit général uniquement)
HIST_METRICS = {
    "heart_rate": ("❤️ HR", "bpm", "hr"),
    "spo2": ("🫁 SpO₂", "%", "spo2"),
    "temperature": ("🌡 Température", "°C", "temp"),
    "hrv": ("💓 HRV", "ms", "hrv"),
    "blood_pressure": ("🩺 Tension", "mmHg", "bp"),
    "stress": ("⚡ Stress", "", "stress"),
    #"fatigue": ("😴 Fatigue", "", None),
    #"health_check": ("🩺 Health-check", "", None),
}

HIST_PERIODS = {1: "1 h", 24: "24 h", 168: "7 jours / 7 days", 720: "30 jours / 30 days", 0: "Tout / All"}


def history_metric_allowed(access, metric):
    allowed = access.get("allowed_measures")
    if metric not in HIST_METRICS:
        return False
    if not allowed:
        return True
    key = HIST_METRICS[metric][2]
    return key is not None and key in allowed


def get_history_metric_counts(ring_id):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT metric, COUNT(*) AS n
                FROM ring_measurements
                WHERE ring_id = %s AND metric = ANY(%s)
                GROUP BY metric
                """,
                (int(ring_id), list(HIST_METRICS)),
            )
            return {r["metric"]: int(r["n"]) for r in cur.fetchall()}


def _period_sql(hours):
    if int(hours) <= 0:
        return "", []
    return " AND time >= NOW() - (%s * INTERVAL '1 hour')", [int(hours)]


def get_history_page(ring_id, metric, hours, offset):
    if metric not in HIST_METRICS:
        raise ValueError("Métrique historique non autorisée")

    where, params = _period_sql(hours)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT COUNT(*) AS total,
                       COUNT(value) FILTER (WHERE status = 'ok') AS n_ok,
                       MIN(value) FILTER (WHERE status = 'ok') AS vmin,
                       AVG(value) FILTER (WHERE status = 'ok') AS vavg,
                       MAX(value) FILTER (WHERE status = 'ok') AS vmax
                FROM ring_measurements
                WHERE ring_id = %s AND metric = %s{where}
                """,
                [int(ring_id), metric] + params,
            )
            summary = dict(cur.fetchone() or {})

            cur.execute(
                f"""
                SELECT time, value, samples, unit, status, reason, extra
                FROM ring_measurements
                WHERE ring_id = %s AND metric = %s{where}
                ORDER BY time DESC
                OFFSET %s LIMIT %s
                """,
                [int(ring_id), metric] + params + [max(0, int(offset)), HISTORY_PAGE_SIZE],
            )
            rows = [dict(r) for r in cur.fetchall()]

    return summary, rows


def history_failure_text(status, reason):
    s = str(status or "").lower()
    r = str(reason or "").lower()
    if r in ("ring_removed", "not_worn") or "removed" in r:
        return "🖐 bague retirée"
    if s == "hors_portee" or r in ("device_out_of_range", "device_not_found", "ring_disconnected") or "portee" in s:
        return "🟡 hors portée"
    if s in ("non_connecte",) or r == "gateway_offline":
        return "⚫ non connectée"
    if r == "timeout":
        return "⏱ pas de résultat"
    return f"❌ {r or s or 'échec'}"


def format_history_page(access, metric, hours, offset, summary, rows):
    label, unit, _ = HIST_METRICS[metric]
    total = int(summary.get("total") or 0)
    lines = [f"📊 {access['ring_name']}", f"{label} · {HIST_PERIODS.get(int(hours), f'{hours} h')}"]

    if not total:
        lines += ["", "Aucune donnée / No data."]
        return "\n".join(lines)

    n_ok = int(summary.get("n_ok") or 0)
    if n_ok and metric != "blood_pressure":
        lines.append(
            f"{total} mesures · min {fmt_num(summary.get('vmin'))} · "
            f"moy {fmt_num(summary.get('vavg'))} · max {fmt_num(summary.get('vmax'))} {unit}".rstrip()
        )
    else:
        lines.append(f"{total} mesures")
    lines.append("")

    for row in rows:
        t = row.get("time")
        when = t.astimezone().strftime("%d/%m %H:%M") if hasattr(t, "astimezone") else str(t)
        extra = row.get("extra") or {}
        if str(row.get("status") or "").lower() == "ok":
            if metric == "blood_pressure":
                val = f"{fmt_num(extra.get('sbp', row.get('value')))}/{fmt_num(extra.get('dbp'))} mmHg"
            elif row.get("value") is None and row.get("samples"):
                val = fmt_samples(row.get("samples"))
            else:
                val = f"{fmt_num(row.get('value'))} {unit}".rstrip()
            dur = extra.get("duration_s")
            lines.append(f"{when}  {val}" + (f"  ⏱ {dur} s" if dur is not None else ""))
        else:
            lines.append(f"{when}  {history_failure_text(row.get('status'), row.get('reason'))}")

    first = int(offset) + 1
    last = int(offset) + len(rows)
    lines += ["", f"{first}–{last} sur / of {total}"]
    return "\n".join(lines)


def history_page_keyboard(ring_id, metric, hours, offset, total):
    rows = []
    nav = []
    if offset > 0:
        nav.append(InlineKeyboardButton(
            "⬆️ Plus récentes",
            callback_data=f"hp:{ring_id}:{metric}:{hours}:{max(0, offset - HISTORY_PAGE_SIZE)}",
        ))
    if offset + HISTORY_PAGE_SIZE < total:
        nav.append(InlineKeyboardButton(
            "➕ Plus / More",
            callback_data=f"hp:{ring_id}:{metric}:{hours}:{offset + HISTORY_PAGE_SIZE}",
        ))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("⏱ Autre période / Other period", callback_data=f"histmetric:{ring_id}:{metric}")])
    rows.append([
        InlineKeyboardButton("⬅️ Capteurs", callback_data=f"history:{ring_id}"),
        InlineKeyboardButton("⬅️ Bague", callback_data=f"ring:{ring_id}"),
    ])
    return InlineKeyboardMarkup(rows)


def history_metrics_keyboard(access, counts):
    rid = access["ring_id"]
    buttons = [
        InlineKeyboardButton(f"{HIST_METRICS[m][0]} ({counts[m]})", callback_data=f"histmetric:{rid}:{m}")
        for m in HIST_METRICS
        if counts.get(m) and history_metric_allowed(access, m)
    ]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton("⬅️ Bague / Ring", callback_data=f"ring:{rid}")])
    return InlineKeyboardMarkup(rows)


def history_period_keyboard(ring_id, metric):
    p = lambda h, t: InlineKeyboardButton(t, callback_data=f"histperiod:{ring_id}:{metric}:{h}")
    return InlineKeyboardMarkup([
        [p(1, "1 h"), p(24, "24 h")],
        [p(168, "7 jours"), p(720, "30 jours")],
        [p(0, "Tout / All")],
        [InlineKeyboardButton("⬅️ Capteurs / Sensors", callback_data=f"history:{ring_id}")],
    ])


async def show_history_page(q, access, metric, hours, offset):
    summary, rows = await asyncio.to_thread(get_history_page, access["ring_id"], metric, hours, offset)
    total = int(summary.get("total") or 0)
    await q.edit_message_text(
        format_history_page(access, metric, hours, offset, summary, rows),
        reply_markup=history_page_keyboard(access["ring_id"], metric, hours, offset, total),
    )


async def start_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not await private_only(update):
        return

    user = update.effective_user

    if update.effective_chat:
        clear_ring_overview_sessions(
            update.effective_chat.id
        )

        # /start signifie que l'utilisateur quitte l'écran LIVE.
        await stop_live_sessions_for_chat(
            update.effective_chat.id,
            bot=context.bot,
        )

    try:
        register_user_from_start(user)

    except Exception as exc:
        log.exception("Erreur /start DB")

        await update.effective_message.reply_text(
            f"⚠️ Erreur PostgreSQL : {exc}"
        )
        return

    # --------------------------------------------------------
    # QR DEEP LINK :
    # https://t.me/BOT?start=pair_<token>
    # --------------------------------------------------------
    start_arg = (
        context.args[0]
        if context.args
        else ""
    )

    if start_arg.startswith("pair_"):
        token = start_arg[len("pair_"):]

        try:
            result = create_pairing_request(
                user.id,
                token,
            )

        except Exception as exc:
            log.exception(
                "Erreur demande QR"
            )
            await update.effective_message.reply_text(
                "⚠️ Erreur lors de la demande "
                "d'appariement / Pairing request error.\n"
                f"{exc}"
            )
            return

        status = result.get("status")

        if status == "invalid":
            await update.effective_message.reply_text(
                "❌ QR invalide ou expiré / "
                "Invalid or expired QR code."
            )
            return

        if status == "already_assigned":
            await update.effective_message.reply_text(
                "✅ Cette bague est déjà affectée "
                "à ton compte / This ring is already "
                "assigned to your account.\n\n"
                f"💍 {result['ring_name']}"
            )
            return

        if status == "already_pending":
            await update.effective_message.reply_text(
                "⏳ Une demande est déjà en attente / "
                "A pairing request is already pending.\n\n"
                f"💍 {result['ring_name']}"
            )
            return

        await update.effective_message.reply_text(
            "📲 Demande d'appariement reçue / "
            "Pairing request received\n\n"
            f"💍 {result['ring_name']}\n"
            f"📡 MAC : {result['mac']}\n\n"
            "La demande a été envoyée à l'administrateur.\n"
            "The request was sent to the administrator."
        )

        await notify_pairing_admins(
            context,
            result,
            user,
        )
        return

    rings = get_accessible_rings(
        user.id
    )

    if not rings:
        bienvenue =("✅ Connexion Telegram enregistrée / "
                    "Telegram connection registered.\n\n"
                    "Aucune bague ne t'est encore affectée.\n"
                    "No ring is assigned to your account yet.\n\n"
                    "Tu peux aussi scanner le QR de la bague "
                    "pour demander son appariement.\n"
                    "You can also scan the ring QR code "
                    "to request pairing.")
        user = update.message.from_user
        if user.last_name is None:
                    print("Username is empty.")
                    last_name = "no_last_name"
        else:
                print(f"Username is: {user.last_name}")
                last_name = user.last_name
        if user.first_name is None:
                print("Username is empty.")
                first_name = "no_firstname"
        else:
                print(f"Username is: {user.last_name}")
                first_name = user.first_name
        if user.username is None:
                print("Username is empty.")
                pseudo = "no_username"
        else:
                print(f"Username is: {user.username}")
                pseudo = user.username
        last_name = user.last_name
        name = f"{first_name} {last_name}" if last_name and last_name != "NONE" else first_name
        await update.effective_message.reply_text(
            
      f"Bienvenue / Welcome, {name} ID_Telegram : ({user.id})\n"
           f"Connexion au bot REMOTE HEALTH MONITORING enregistrée.\n"
            f"Aucune bague ne vous est encore affectée.\n\n"
           f"Connection to the REMOTE HEALTH MONITORING bot recorded.\n"
            f"No ring is assigned to your account yet.\n")
        return

    await update.effective_message.reply_text(
        "💍 Mes rings / My rings",
        reply_markup=rings_keyboard(
            rings
        ),
    )


async def rings_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not await private_only(update):
        return

    user = update.effective_user

    if update.effective_chat:
        clear_ring_overview_sessions(
            update.effective_chat.id
        )

        # Aller vers "Mes rings" ferme toute session LIVE de ce chat.
        await stop_live_sessions_for_chat(
            update.effective_chat.id,
            bot=context.bot,
        )

    rings = get_accessible_rings(
        user.id
    )

    text = (
        "💍 Mes rings / My rings"
        if rings
        else (
            "Aucune bague affectée / "
            "No ring assigned."
        )
    )

    markup = (
        rings_keyboard(rings)
        if rings
        else None
    )

    if update.callback_query:
        await update.callback_query.answer()

        await update.callback_query.edit_message_text(
            text,
            reply_markup=markup,
        )

    else:
        await update.effective_message.reply_text(
            text,
            reply_markup=markup,
        )


async def callback_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not await private_only(update):
        return

    q = update.callback_query
    user = update.effective_user
    data = q.data or ""

    # Le clic signifie que l'utilisateur quitte éventuellement
    # l'écran Ring précédent. On stoppe son auto-refresh avant
    # de changer le contenu du message.
    if q.message:
        clear_ring_overview_sessions(
            q.message.chat_id
        )

        # Naviguer ailleurs depuis ce message arrête le suivi de sa mesure
        # (sauf « État » qui la garde affichée, et un nouveau clic de mesure).
        if not data.startswith(("ms:", "st:")):
            drop_tracker(
                q.message.chat_id,
                q.message.message_id,
            )

        # L'écran de bague n'est plus affiché dans ce message : plus de mise à jour automatique
        if not data.startswith(("ms:", "st:", "ring:")):
            unwatch_ring_message(
                q.message.chat_id,
                q.message.message_id,
            )

    # --------------------------------------------------------
    # ADMIN : APPROBATION QR
    # --------------------------------------------------------
    if data.startswith("pairapprove:"):
        if not is_global_admin(user.id):
            await q.answer(
                "Admin uniquement / Admin only.",
                show_alert=True,
            )
            return

        await q.answer()

        request_id = int(
            data.split(":", 1)[1]
        )

        try:
            row = approve_pairing_request(
                request_id,
                user.id,
            )

            if not row:
                await q.edit_message_text(
                    "❌ Demande introuvable / "
                    "Request not found."
                )
                return

            if row.get("result") == "already_decided":
                await q.edit_message_text(
                    "ℹ️ Demande déjà traitée / "
                    "Request already processed."
                )
                return

            await q.edit_message_text(
                "✅ Appariement autorisé / "
                "Pairing approved\n\n"
                f"💍 {row['ring_name']}\n"
                f"👤 Telegram ID : {row['id_telegram']}"
            )

            try:
                await send_assignment_notification_bot(
                    context.bot,
                    chat_id=row["id_telegram"],
                    ring_id=row["ring_id"],
                    ring_name=row["ring_name"],
                    mac=row["mac"],
                    first_name=row.get(
                        "firstname"
                    ),
                )
            except Exception:
                log.exception(
                    "Notification affectation QR impossible"
                )

        except Exception as exc:
            log.exception(
                "Erreur approbation QR"
            )
            await q.edit_message_text(
                "⚠️ Erreur / Error : "
                f"{exc}"
            )

        return

    # --------------------------------------------------------
    # ADMIN : REFUS QR
    # --------------------------------------------------------
    if data.startswith("pairreject:"):
        if not is_global_admin(user.id):
            await q.answer(
                "Admin uniquement / Admin only.",
                show_alert=True,
            )
            return

        await q.answer()

        request_id = int(
            data.split(":", 1)[1]
        )

        try:
            row = reject_pairing_request(
                request_id,
                user.id,
            )

            if not row:
                await q.edit_message_text(
                    "❌ Demande introuvable / "
                    "Request not found."
                )
                return

            if row.get("result") == "already_decided":
                await q.edit_message_text(
                    "ℹ️ Demande déjà traitée / "
                    "Request already processed."
                )
                return

            await q.edit_message_text(
                "❌ Appariement refusé / "
                "Pairing rejected\n\n"
                f"💍 {row['ring_name']}"
            )

            try:
                await context.bot.send_message(
                    chat_id=int(
                        row["id_telegram"]
                    ),
                    text=(
                        "❌ Demande d'appariement refusée / "
                        "Pairing request rejected\n\n"
                        f"💍 {row['ring_name']}\n"
                        f"📡 MAC : {row['mac']}"
                    ),
                )
            except Exception:
                log.exception(
                    "Notification refus QR impossible"
                )

        except Exception as exc:
            log.exception(
                "Erreur refus QR"
            )
            await q.edit_message_text(
                f"⚠️ Erreur / Error : {exc}"
            )

        return

    if data == "rings":
        await rings_handler(
            update,
            context,
        )
        return

    if data.startswith("ring:"):
        await q.answer()

        ring_id = int(
            data.split(":")[1]
        )

        # Retour volontaire vers l'écran de la bague :
        # une éventuelle session LIVE (ancienne Pi400) de cette bague est terminée.
        await stop_live_sessions_for_chat(
            q.message.chat_id,
            ring_id=ring_id,
            bot=context.bot,
        )

        access = await asyncio.to_thread(
            get_ring_access,
            user.id,
            ring_id,
        )

        if not access:
            await q.edit_message_text(
                "⛔ Accès refusé / Access denied."
            )
            return

        await show_ring_screen(
            context.bot,
            q.message.chat_id,
            q.message.message_id,
            access,
        )
        return

    # --------------------------------------------------------
    # ÉTAT : actualise l'écran et vérifie le port de la bague
    # --------------------------------------------------------
    if data.startswith("st:"):
        await start_wear_check(update, context, int(data.split(":")[1]))
        return

    # --------------------------------------------------------
    # MESURE À LA DEMANDE : ms:<ring_id>:<hr|spo2|hrv|temp>
    # --------------------------------------------------------
    if data.startswith("ms:"):
        _, ring_raw, key = data.split(":", 2)
        await start_measure(update, context, int(ring_raw), key)
        return

    # --------------------------------------------------------
    # INFOS
    # --------------------------------------------------------
    if data.startswith("inf:"):
        ring_id = int(data.split(":")[1])

        access = await asyncio.to_thread(get_ring_access, user.id, ring_id)

        if not access:
            await q.answer("⛔ Accès refusé / Access denied.", show_alert=True)
            return

        await q.answer()
        ring = live_ring(access["mac"])
        await q.edit_message_text(
            format_ring_info(access, ring),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔄 Actualiser", callback_data=f"inf:{ring_id}"),
                InlineKeyboardButton("⬅️ Bague / Ring", callback_data=f"ring:{ring_id}"),
            ]]),
        )
        return

    if data.startswith("live:"):
        await q.answer()

        ring_id = int(
            data.split(":")[1]
        )

        access = get_ring_access(
            user.id,
            ring_id,
        )

        if (
            not access
            or not access["can_live"]
        ):
            await q.answer(
                "LIVE non autorisé / "
                "LIVE not allowed.",
                show_alert=True,
            )
            return

        state = seed_live_state_from_db(
            ring_id
        )

        await q.edit_message_text(
            format_live(
                access["ring_name"],
                state,
            ),
            reply_markup=live_keyboard(
                ring_id
            ),
        )

        session = {
            "telegram_user_id":
                int(
                    access[
                        "telegram_user_id"
                    ]
                ),
            "ring_id": ring_id,
            "ring_name":
                access["ring_name"],
            "chat_id":
                int(q.message.chat_id),
            "message_id":
                int(q.message.message_id),
            "last_edit": 0.0,
            "expires_at":
                time.time()
                + LIVE_SESSION_MINUTES
                * 60,
            "warning_sent": False,
        }

        with live_sessions_lock:
            live_sessions[
                (
                    session["chat_id"],
                    ring_id,
                )
            ] = session

        db_start_live_session(
            session["telegram_user_id"],
            ring_id,
            session["chat_id"],
            session["message_id"],
        )
        return


    if data.startswith("refreshlive:"):
        ring_id = int(
            data.split(":")[1]
        )

        access = get_ring_access(
            user.id,
            ring_id,
        )

        if (
            not access
            or not access["can_live"]
        ):
            await q.answer(
                "LIVE non autorisé / LIVE not allowed.",
                show_alert=True,
            )
            return

        try:
            # Resynchronisation DB + cache LIVE.
            state = seed_live_state_from_db(
                ring_id
            )

            try:
                await q.edit_message_text(
                    format_live(
                        access["ring_name"],
                        state,
                    ),
                    reply_markup=live_keyboard(
                        ring_id
                    ),
                )

            except BadRequest as exc:
                # Si le contenu n'a pas changé, le refresh a quand même réussi.
                if (
                    "message is not modified"
                    not in str(exc).lower()
                ):
                    raise

            await q.answer(
                "✅ LIVE actualisé / LIVE refreshed",
                show_alert=True,
            )

        except Exception as exc:
            log.exception(
                "Erreur refresh manuel LIVE"
            )

            await q.answer(
                "⚠️ Actualisation impossible / Refresh failed\n"
                f"{exc}",
                show_alert=True,
            )

        return


    if data.startswith("extendlive:"):
        ring_id = int(
            data.split(":")[1]
        )

        key = (
            int(q.message.chat_id),
            ring_id,
        )

        warning_message_id = None

        with live_sessions_lock:
            session = live_sessions.get(
                key
            )

            if session:
                warning_message_id = session.pop(
                    "warning_message_id",
                    None,
                )

                session["expires_at"] = (
                    time.time()
                    + LIVE_SESSION_MINUTES
                    * 60
                )
                session["warning_sent"] = False

        if warning_message_id:
            try:
                await context.bot.delete_message(
                    chat_id=q.message.chat_id,
                    message_id=warning_message_id,
                )
            except Exception:
                pass

        if not session:
            await q.answer(
                "LIVE déjà arrêté / LIVE already stopped.",
                show_alert=True,
            )
            return

        try:
            db_extend_live_session(
                session[
                    "telegram_user_id"
                ],
                ring_id,
                session["chat_id"],
                LIVE_SESSION_MINUTES,
            )

        except Exception:
            log.exception(
                "Erreur prolongation LIVE DB"
            )

        try:
            await q.edit_message_text(
                "✅ LIVE prolongé / LIVE extended\n\n"
                f"+ {LIVE_SESSION_MINUTES} min"
            )

        except Exception:
            pass

        await q.answer(
            (
                "✅ LIVE prolongé de "
                f"{LIVE_SESSION_MINUTES} min / "
                "LIVE extended"
            ),
            show_alert=True,
        )

        return


    if data.startswith("stoplive:"):
        await q.answer()

        ring_id = int(
            data.split(":")[1]
        )

        await stop_live_sessions_for_chat(
            q.message.chat_id,
            ring_id=ring_id,
            bot=context.bot,
        )

        await q.edit_message_text(
            "⏹ LIVE arrêté / LIVE stopped.",
            reply_markup=InlineKeyboardMarkup(
                [[
                    InlineKeyboardButton(
                        "⬅️ Ring",
                        callback_data=(
                            f"ring:{ring_id}"
                        ),
                    )
                ]]
            ),
        )
        return

    # --------------------------------------------------------
    # HISTORIQUE : capteur puis durée
    # --------------------------------------------------------
    if data.startswith("history:"):
        ring_id = int(
            data.split(":")[1]
        )

        # Passer à l'historique est une sortie volontaire du LIVE.
        await stop_live_sessions_for_chat(
            q.message.chat_id,
            ring_id=ring_id,
            bot=context.bot,
        )

        access = await asyncio.to_thread(get_ring_access, user.id, ring_id)

        if not access or not access["can_view_history"]:
            await q.answer(
                "Historique non autorisé / History not allowed.",
                show_alert=True,
            )
            return

        await q.answer()

        counts = await asyncio.to_thread(get_history_metric_counts, ring_id)
        visible = [m for m in HIST_METRICS if counts.get(m) and history_metric_allowed(access, m)]

        await q.edit_message_text(
            f"📊 Historique — {access['ring_name']}\n"
            + (
                "Choisis le capteur / Choose sensor:"
                if visible
                else "Aucune mesure enregistrée / No measurement recorded."
            ),
            reply_markup=history_metrics_keyboard(access, counts),
        )
        return

    if data.startswith("histmetric:"):
        _, ring_raw, metric = data.split(":", 2)
        ring_id = int(ring_raw)

        access = await asyncio.to_thread(get_ring_access, user.id, ring_id)

        if (
            not access
            or not access["can_view_history"]
            or not history_metric_allowed(access, metric)
        ):
            await q.answer(
                "Historique non autorisé / History not allowed.",
                show_alert=True,
            )
            return

        await q.answer()

        await q.edit_message_text(
            f"📊 {access['ring_name']}\n"
            f"{HIST_METRICS[metric][0]}\n\n"
            "Choisis la durée / Choose period:",
            reply_markup=history_period_keyboard(ring_id, metric),
        )
        return

    # histperiod:<ring>:<metric>:<heures>        -> première page
    # hp:<ring>:<metric>:<heures>:<décalage>     -> bouton « Plus » / « Plus récentes »
    if data.startswith("histperiod:") or data.startswith("hp:"):
        parts = data.split(":")
        ring_id = int(parts[1])
        metric = parts[2]
        hours = int(parts[3])
        offset = int(parts[4]) if len(parts) > 4 else 0

        access = await asyncio.to_thread(get_ring_access, user.id, ring_id)

        if (
            not access
            or not access["can_view_history"]
            or not history_metric_allowed(access, metric)
        ):
            await q.answer(
                "Historique non autorisé / History not allowed.",
                show_alert=True,
            )
            return

        await q.answer()

        try:
            await show_history_page(q, access, metric, hours, offset)
        except BadRequest as exc:
            if "not modified" not in str(exc).lower():
                raise
        return

    await q.answer(
        "Commande inconnue / Unknown command."
    )


async def status_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not await private_only(update):
        return

    try:
        row = db_healthcheck()

        with android_lock:
            seen = sum(1 for r in android_rings.values() if r["statusTs"])
        mq = "connecté" if (mqtt_client_ref and mqtt_client_ref.is_connected()) else "déconnecté"

        await update.effective_message.reply_text(
            "✅ DANY Telegram Bot\n"
            f"PostgreSQL : OK ({row['db']})\n"
            f"Utilisateur DB : {row['usr']}\n"
            f"MQTT : {MQTT_HOST}:{MQTT_PORT}\n"
            f"Topic : {MQTT_TOPIC}\n"
            f"Admins : {len(TELEGRAM_ADMIN_IDS)}\n"
            f"MQTT : {mq} · bagues vues : {seen}\n"
            f"Mesures suivies : {len(measure_trackers)}"
        )

    except Exception as exc:
        await update.effective_message.reply_text(
            f"⚠️ PostgreSQL : {exc}"
        )



async def cleanup_live_sessions(
    context: ContextTypes.DEFAULT_TYPE,
):
    """
    Contrôle périodique des sessions LIVE.

    - < LIVE_WARNING_MINUTES : une notification UNE seule fois.
    - expiration : arrêt du LIVE.
    - HORS PORTEE ne ferme jamais le LIVE.
    """
    now = time.time()
    warning_seconds = (
        LIVE_WARNING_MINUTES
        * 60
    )

    warnings = []
    expired = []

    with live_sessions_lock:
        for key, session in list(
            live_sessions.items()
        ):
            remaining = (
                session["expires_at"]
                - now
            )

            if remaining <= 0:
                expired.append(
                    (
                        key,
                        dict(session),
                    )
                )
                continue

            if (
                remaining
                <= warning_seconds
                and not session.get(
                    "warning_sent",
                    False,
                )
            ):
                # Marquer avant envoi pour éviter plusieurs warnings.
                session["warning_sent"] = True

                warnings.append(
                    (
                        key,
                        dict(session),
                        remaining,
                    )
                )

    # --------------------------------------------------------
    # WARNING LIVE
    # --------------------------------------------------------
    for key, session, remaining in warnings:
        try:
            mins = max(
                1,
                int(
                    remaining // 60
                )
            )

            # Re-vérifier juste avant l'envoi :
            # l'utilisateur a peut-être quitté LIVE entre le scan
            # des sessions et ce point.
            with live_sessions_lock:
                still_active = (
                    key in live_sessions
                )

            if not still_active:
                continue

            sent_warning = await context.bot.send_message(
                chat_id=
                    session["chat_id"],
                text=(
                    "⚠️ LIVE bientôt arrêté / "
                    "LIVE ending soon\n\n"
                    f"💍 {session['ring_name']}\n\n"
                    "Le LIVE s'arrêtera automatiquement "
                    f"dans moins de {LIVE_WARNING_MINUTES} minutes.\n"
                    "The LIVE will stop automatically "
                    f"in less than {LIVE_WARNING_MINUTES} minutes.\n\n"
                    f"Temps restant approximatif / "
                    f"Approx. remaining: {mins} min"
                ),
                reply_markup=
                    InlineKeyboardMarkup(
                        [[
                            InlineKeyboardButton(
                                (
                                    "🔄 Prolonger "
                                    f"{LIVE_SESSION_MINUTES} min / "
                                    "Extend"
                                ),
                                callback_data=(
                                    f"extendlive:"
                                    f"{session['ring_id']}"
                                ),
                            )
                        ]]
                    ),
            )

            # Mémoriser le warning uniquement si LIVE est encore actif.
            # Si l'utilisateur a quitté LIVE pendant l'appel Telegram,
            # supprimer immédiatement le warning qui vient d'être envoyé.
            delete_immediately = False

            with live_sessions_lock:
                current = live_sessions.get(
                    key
                )

                if current:
                    current[
                        "warning_message_id"
                    ] = sent_warning.message_id
                else:
                    delete_immediately = True

            if delete_immediately:
                try:
                    await context.bot.delete_message(
                        chat_id=
                            session["chat_id"],
                        message_id=
                            sent_warning.message_id,
                    )
                except Exception:
                    pass

        except Exception:
            log.exception(
                "Erreur warning fin LIVE"
            )

    # --------------------------------------------------------
    # EXPIRATION
    # --------------------------------------------------------
    for key, session in expired:
        with live_sessions_lock:
            live_sessions.pop(
                key,
                None,
            )

        try:
            db_stop_live_session(
                session[
                    "telegram_user_id"
                ],
                session["ring_id"],
                session["chat_id"],
            )

        except Exception:
            log.exception(
                "Erreur stop session DB"
            )

        try:
            await context.bot.edit_message_text(
                chat_id=
                    session["chat_id"],
                message_id=
                    session["message_id"],
                text=(
                    "⏹ LIVE arrêté automatiquement / "
                    "LIVE stopped automatically after "
                    f"{LIVE_SESSION_MINUTES} min."
                ),
            )

        except Exception:
            pass

# ============================================================
# MAIN
# ============================================================

async def post_init(app):
    global telegram_loop

    telegram_loop = asyncio.get_running_loop()
    await recover_measure_trackers(app.bot)
    load_alerts()

    # Suivi des mesures (en cours → résultat) et des écrans de bague : boucle propre au bot,
    # indépendante de la job-queue (qui peut manquer selon l'installation).
    app.create_task(measure_loop(app.bot))

    log.info("Telegram bot prêt")


def validate_config():
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN absent du fichier .env"
        )

    if not DB_USER:
        raise RuntimeError(
            "DB_USER absent du fichier .env"
        )


def main():
    global telegram_app

    validate_config()

    health = db_healthcheck()

    log.info(
        "PostgreSQL OK : db=%s user=%s",
        health["db"],
        health["usr"],
    )

    if not TELEGRAM_ADMIN_IDS:
        log.warning(
            "TELEGRAM_ADMIN_IDS vide : "
            "les demandes QR seront enregistrées "
            "mais aucun admin ne recevra les boutons."
        )

    mqtt_client = start_mqtt()

    telegram_app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    telegram_app.add_handler(
        CommandHandler(
            "start",
            start_handler,
        )
    )

    telegram_app.add_handler(
        CommandHandler(
            "rings",
            rings_handler,
        )
    )

    telegram_app.add_handler(
        CommandHandler(
            "status",
            status_handler,
        )
    )

    telegram_app.add_handler(
        CallbackQueryHandler(
            callback_handler
        )
    )

    if telegram_app.job_queue:
        telegram_app.job_queue.run_repeating(
            cleanup_live_sessions,
            interval=60,
            first=60,
        )
    else:
        log.warning(
            "job-queue absente (pip install 'python-telegram-bot[job-queue]') : "
            "nettoyage des anciennes sessions LIVE désactivé."
        )

    try:
        telegram_app.run_polling(
            allowed_updates=
                Update.ALL_TYPES,
        )

    finally:
        mqtt_client.loop_stop()
        mqtt_client.disconnect()


if __name__ == "__main__":
    main()
