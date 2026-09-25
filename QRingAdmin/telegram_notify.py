"""
Notifications Telegram envoyées par QRing Admin.
Mêmes textes et mêmes boutons que l'ancien admin DANY (app.py n'est pas modifié).
"""
import json
import os
import urllib.error
import urllib.request

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()


def send_message(chat_id, text, reply_markup=None):
    """Retourne (True, None) ou (False, raison)."""
    if not TELEGRAM_BOT_TOKEN:
        return False, "TELEGRAM_BOT_TOKEN absent du .env"
    if not chat_id:
        return False, "id_telegram absent"
    payload = {"chat_id": int(chat_id), "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            res = json.loads(r.read().decode("utf-8"))
        return (True, None) if res.get("ok") else (False, res.get("description") or "Erreur Telegram")
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8", "replace"))
            return False, body.get("description") or str(e)
        except Exception:
            return False, str(e)
    except Exception as e:
        return False, str(e)


def ring_assigned(user, ring):
    first = user.get("firstname") or ""
    hello = f" {first}" if first else ""
    text = (
        f"✅ Nouvelle bague affectée / New ring assigned{hello}\n\n"
        f"💍 {ring.get('name') or 'COLMI Ring'}\n"
        f"📡 MAC : {ring.get('mac') or ''}\n\n"
        "La bague est maintenant disponible dans ton bot DANY.\n"
        "The ring is now available in your DANY bot.\n\n"
        "Tu peux consulter les mesures et l'historique selon tes droits.\n"
        "You can view measurements and history according to your permissions."
    )
    markup = None
    if ring.get("id"):
        markup = {"inline_keyboard": [[{"text": "💍 Ouvrir la bague / Open ring", "callback_data": f"ring:{ring['id']}"}]]}
    return send_message(user.get("id_telegram"), text, markup)


def ring_unassigned(user, ring):
    text = (
        "ℹ️ Bague désaffectée / Ring unassigned\n\n"
        f"💍 {ring.get('name') or 'COLMI Ring'}\n"
        f"📡 MAC : {ring.get('mac') or ''}\n\n"
        "Cette bague n'est plus affectée à ton compte.\n"
        "This ring is no longer assigned to your account."
    )
    return send_message(user.get("id_telegram"), text)


def pairing_rejected(row):
    text = (
        "❌ Demande d'appariement refusée / Pairing request rejected\n\n"
        f"💍 {row.get('ring_name') or 'COLMI Ring'}\n"
        f"📡 MAC : {row.get('mac') or ''}\n\n"
        "La demande d'affectation n'a pas été autorisée.\n"
        "The pairing request was not approved."
    )
    return send_message(row.get("id_telegram"), text)
