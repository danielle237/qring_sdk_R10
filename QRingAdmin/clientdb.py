"""
QRingClient — requêtes PostgreSQL des comptes de l'app téléphone.

Utilisé par :
- client_api.py  (service de l'app QRingClient, indépendant de QRing Admin)
- app.py         (page « Comptes app » de QRing Admin)

Tables créées par client_migration.sql : client_users, client_ring_access, client_devices, client_alerts.
La connexion (paramètres DB_* du .env) est celle de dbq.py.
"""
from datetime import datetime, timedelta, timezone

from werkzeug.security import check_password_hash, generate_password_hash

import dbq

# Mesures qu'un compte peut être autorisé à lancer (NULL en base = toutes)
CLIENT_MEASURES = ["hr", "spo2", "temp", "bp", "hrv", "stress", "fatigue", "health", "steps"]
LANGS = ("fr", "en", "ar")
MAX_FAILED_LOGINS = 5
LOCK_MINUTES = 5

USER_COLS = """u.id, u.login, u.display_name, u.lang, u.active, u.alerts_enabled, u.token_version,
               u.failed_logins, u.locked_until, u.last_login_at, u.created_at, u.updated_at"""


def _now():
    return datetime.now(timezone.utc)


def tables_ready():
    """True si client_migration.sql a été lancé."""
    try:
        with dbq.connect() as c:
            row = c.execute("SELECT to_regclass('public.client_users') IS NOT NULL AS ok").fetchone()
            return bool(row and row["ok"])
    except Exception:
        return False


def _clean_measures(values):
    if values is None:
        return None
    vals = [v for v in values if v in CLIENT_MEASURES]
    return vals or None


# =============================================================================
# COMPTES
# =============================================================================

def list_users():
    with dbq.connect() as c:
        return c.execute(
            f"""SELECT {USER_COLS},
                       COALESCE(json_agg(json_build_object('access_id', a.id, 'ring_id', r.id, 'name', r.name,
                                'label', a.label, 'mac', r.mac::text, 'active', a.active)
                                ORDER BY r.name) FILTER (WHERE a.id IS NOT NULL), '[]') AS rings,
                       (SELECT COUNT(*) FROM client_devices d WHERE d.client_user_id = u.id) AS devices
                FROM client_users u
                LEFT JOIN client_ring_access a ON a.client_user_id = u.id
                LEFT JOIN rings r ON r.id = a.ring_id
                GROUP BY u.id
                ORDER BY u.active DESC, lower(u.login)"""
        ).fetchall()


def get_user(user_id):
    with dbq.connect() as c:
        return c.execute(f"SELECT {USER_COLS} FROM client_users u WHERE u.id = %s", (int(user_id),)).fetchone()


def create_user(login, password, display_name=None, lang="fr"):
    login = (login or "").strip().lower()
    if len(login) < 3:
        raise ValueError("Identifiant trop court (3 caractères minimum)")
    if len(password or "") < 6:
        raise ValueError("Mot de passe trop court (6 caractères minimum)")
    with dbq.connect() as c:
        if c.execute("SELECT 1 FROM client_users WHERE login = %s", (login,)).fetchone():
            raise ValueError("Cet identifiant existe déjà")
        return c.execute(
            f"""INSERT INTO client_users (login, password_hash, display_name, lang)
                VALUES (%s, %s, %s, %s) RETURNING {USER_COLS.replace('u.', '')}""",
            (login, generate_password_hash(password), (display_name or "").strip() or None,
             lang if lang in LANGS else "fr"),
        ).fetchone()


def update_user(user_id, data):
    """Modifie nom / langue / actif / mot de passe. Mot de passe ou désactivation => déconnexion des téléphones."""
    sets, args, bump = [], [], False
    if "display_name" in data:
        sets.append("display_name = %s")
        args.append((data.get("display_name") or "").strip() or None)
    if data.get("lang") in LANGS:
        sets.append("lang = %s")
        args.append(data["lang"])
    if "active" in data:
        sets.append("active = %s")
        args.append(bool(data["active"]))
        if not data["active"]:
            bump = True
    if data.get("password"):
        if len(data["password"]) < 6:
            raise ValueError("Mot de passe trop court (6 caractères minimum)")
        sets.append("password_hash = %s")
        args.append(generate_password_hash(data["password"]))
        sets.append("failed_logins = 0")
        sets.append("locked_until = NULL")
        bump = True
    if bump:
        sets.append("token_version = token_version + 1")
    if not sets:
        return get_user(user_id)
    sets.append("updated_at = NOW()")
    with dbq.connect() as c:
        return c.execute(
            f"UPDATE client_users SET {', '.join(sets)} WHERE id = %s RETURNING {USER_COLS.replace('u.', '')}",
            (*args, int(user_id)),
        ).fetchone()


def delete_user(user_id):
    with dbq.connect() as c:
        return bool(c.execute("DELETE FROM client_users WHERE id = %s RETURNING id", (int(user_id),)).fetchone())


def check_login(login, password):
    """Retourne (user, None) si OK, sinon (None, raison). Bloque 5 min après 5 erreurs."""
    login = (login or "").strip().lower()
    with dbq.connect() as c:
        row = c.execute("SELECT * FROM client_users WHERE login = %s", (login,)).fetchone()
        if not row:
            return None, "bad"
        if row["locked_until"] and row["locked_until"] > _now():
            return None, "locked"
        if not check_password_hash(row["password_hash"], password or ""):
            n = row["failed_logins"] + 1
            locked = _now() + timedelta(minutes=LOCK_MINUTES) if n >= MAX_FAILED_LOGINS else None
            c.execute("UPDATE client_users SET failed_logins = %s, locked_until = %s WHERE id = %s",
                      (0 if locked else n, locked, row["id"]))
            return None, "locked" if locked else "bad"
        if not row["active"]:
            return None, "disabled"
        c.execute("UPDATE client_users SET failed_logins = 0, locked_until = NULL, last_login_at = NOW() WHERE id = %s",
                  (row["id"],))
        row.pop("password_hash", None)
        return row, None


def change_password(user_id, old, new):
    with dbq.connect() as c:
        row = c.execute("SELECT password_hash FROM client_users WHERE id = %s", (int(user_id),)).fetchone()
    if not row or not check_password_hash(row["password_hash"], old or ""):
        raise PermissionError("Ancien mot de passe incorrect")
    return update_user(user_id, {"password": new})


def set_prefs(user_id, data):
    sets, args = [], []
    if "alerts_enabled" in data:
        sets.append("alerts_enabled = %s")
        args.append(bool(data["alerts_enabled"]))
    if data.get("lang") in LANGS:
        sets.append("lang = %s")
        args.append(data["lang"])
    if not sets:
        return get_user(user_id)
    with dbq.connect() as c:
        return c.execute(
            f"UPDATE client_users SET {', '.join(sets)}, updated_at = NOW() WHERE id = %s RETURNING {USER_COLS.replace('u.', '')}",
            (*args, int(user_id)),
        ).fetchone()


# =============================================================================
# BAGUES ET DROITS
# =============================================================================

ACCESS_COLS = """a.id AS access_id, a.client_user_id, a.label, a.can_view_history, a.can_live, a.allowed_measures,
                 a.can_receive_alerts, a.notify, a.active, a.updated_at,
                 r.id AS ring_id, r.name AS ring_name, r.mac::text AS mac, r.model"""


def user_rings(user_id):
    """Bagues actives d'un compte (pour l'app)."""
    with dbq.connect() as c:
        return c.execute(
            f"""SELECT {ACCESS_COLS} FROM client_ring_access a JOIN rings r ON r.id = a.ring_id
                WHERE a.client_user_id = %s AND a.active AND r.active
                ORDER BY COALESCE(a.label, r.name), r.mac""",
            (int(user_id),),
        ).fetchall()


def list_access(user_id):
    """Toutes les affectations d'un compte (page admin)."""
    with dbq.connect() as c:
        return c.execute(
            f"""SELECT {ACCESS_COLS} FROM client_ring_access a JOIN rings r ON r.id = a.ring_id
                WHERE a.client_user_id = %s ORDER BY COALESCE(a.label, r.name), r.mac""",
            (int(user_id),),
        ).fetchall()


def all_rings():
    with dbq.connect() as c:
        return c.execute(
            "SELECT id, name, mac::text AS mac, model FROM rings WHERE active ORDER BY name NULLS LAST, mac"
        ).fetchall()


def upsert_access(user_id, data):
    ring_id = int(data.get("ring_id") or 0)
    if not ring_id:
        raise ValueError("Bague manquante")
    measures = data.get("allowed_measures")
    measures = None if measures in (None, "all") else _clean_measures(list(measures))
    with dbq.connect() as c:
        row = c.execute(
            """INSERT INTO client_ring_access (client_user_id, ring_id, label, can_view_history, can_live,
                                               allowed_measures, can_receive_alerts, active)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (client_user_id, ring_id) DO UPDATE SET
                   label = EXCLUDED.label, can_view_history = EXCLUDED.can_view_history,
                   can_live = EXCLUDED.can_live, allowed_measures = EXCLUDED.allowed_measures,
                   can_receive_alerts = EXCLUDED.can_receive_alerts, active = EXCLUDED.active, updated_at = NOW()
               RETURNING id""",
            (int(user_id), ring_id, (data.get("label") or "").strip() or None,
             bool(data.get("can_view_history", True)), bool(data.get("can_live", True)), measures,
             bool(data.get("can_receive_alerts", True)), bool(data.get("active", True))),
        ).fetchone()
    return row["id"]


def delete_access(user_id, access_id):
    with dbq.connect() as c:
        return bool(c.execute("DELETE FROM client_ring_access WHERE id = %s AND client_user_id = %s RETURNING id",
                              (int(access_id), int(user_id))).fetchone())


def set_notify(user_id, notify, mac=None):
    """Choix de l'utilisateur : alertes pour une bague (mac) ou pour toutes (mac=None)."""
    with dbq.connect() as c:
        if mac:
            c.execute("""UPDATE client_ring_access a SET notify = %s, updated_at = NOW()
                         FROM rings r WHERE r.id = a.ring_id AND a.client_user_id = %s AND r.mac = %s::macaddr""",
                      (bool(notify), int(user_id), mac))
        else:
            c.execute("UPDATE client_ring_access SET notify = %s, updated_at = NOW() WHERE client_user_id = %s",
                      (bool(notify), int(user_id)))


# =============================================================================
# ALERTES ET TÉLÉPHONES (FCM)
# =============================================================================

def recipients(ring_id):
    """Comptes qui doivent recevoir les alertes d'une bague : droit admin + choix bague + choix général."""
    with dbq.connect() as c:
        return c.execute(
            """SELECT u.id AS user_id, u.lang, COALESCE(a.label, r.name) AS label
               FROM client_ring_access a
               JOIN client_users u ON u.id = a.client_user_id
               JOIN rings r ON r.id = a.ring_id
               WHERE a.ring_id = %s AND a.active AND a.can_receive_alerts AND a.notify
                 AND u.active AND u.alerts_enabled""",
            (int(ring_id),),
        ).fetchall()


def add_alert(ring_id, kind, title, message):
    with dbq.connect() as c:
        return c.execute(
            "INSERT INTO client_alerts (ring_id, kind, title, message) VALUES (%s, %s, %s, %s) RETURNING id, created_at",
            (int(ring_id), kind, title, message),
        ).fetchone()


def user_alerts(user_id, limit=50):
    """Dernières alertes des bagues du compte (droit « alertes »)."""
    with dbq.connect() as c:
        return c.execute(
            """SELECT al.id, al.kind, al.title, al.message, al.created_at, r.mac::text AS mac,
                      COALESCE(a.label, r.name) AS label
               FROM client_alerts al
               JOIN client_ring_access a ON a.ring_id = al.ring_id AND a.client_user_id = %s AND a.active
                                          AND a.can_receive_alerts
               JOIN rings r ON r.id = al.ring_id
               WHERE al.created_at >= GREATEST(a.created_at, NOW() - INTERVAL '30 days')
               ORDER BY al.created_at DESC LIMIT %s""",
            (int(user_id), int(limit)),
        ).fetchall()


def add_device(user_id, token, platform=None, app_version=None):
    with dbq.connect() as c:
        c.execute(
            """INSERT INTO client_devices (client_user_id, fcm_token, platform, app_version)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (fcm_token) DO UPDATE SET client_user_id = EXCLUDED.client_user_id,
                   platform = EXCLUDED.platform, app_version = EXCLUDED.app_version, last_seen_at = NOW()""",
            (int(user_id), token, platform, app_version),
        )


def remove_device(token):
    with dbq.connect() as c:
        c.execute("DELETE FROM client_devices WHERE fcm_token = %s", (token,))


def device_tokens(user_ids):
    if not user_ids:
        return []
    with dbq.connect() as c:
        return c.execute(
            "SELECT client_user_id AS user_id, fcm_token FROM client_devices WHERE client_user_id = ANY(%s)",
            (list(user_ids),),
        ).fetchall()


def ring_id_by_mac(mac):
    with dbq.connect() as c:
        row = c.execute("SELECT id FROM rings WHERE mac = %s::macaddr", (mac,)).fetchone()
    return row["id"] if row else None
