"""
Photos des résidents (une par bague), partagées par l'admin (app.py) et le Client RHM (client_api.py).

  photos/<MAC12>.jpg        (dossier PHOTO_DIR du .env, par défaut QRingAdmin/photos)

La version d'une photo = son heure de modification : l'admin la publie sur MQTT
(eis/colmi/config/photos, retenu) → client_api pousse la nouvelle version à l'app, qui recharge l'image.
Pillow (pip install Pillow) : photo recadrée en carré 512 px et enregistrée en JPEG ; sans Pillow,
le fichier JPEG / PNG envoyé est gardé tel quel.
"""
import io
import os
import re
import time

PHOTO_DIR = os.getenv("PHOTO_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "photos")
MAX_BYTES = 8 * 1024 * 1024
SIZE = 512

try:
    from PIL import Image, ImageOps
except ImportError:          # Pillow absent : fichier gardé tel quel
    Image = None


def _mac12(mac):
    h = re.sub(r"[^0-9A-Fa-f]", "", str(mac or "")).upper()
    if len(h) != 12:
        raise ValueError("MAC invalide")
    return h


def path_for(mac):
    return os.path.join(PHOTO_DIR, f"{_mac12(mac)}.jpg")


def save(mac, data):
    """Enregistre la photo ; renvoie sa version (heure). ValueError si le fichier n'est pas une image."""
    if not data:
        raise ValueError("Fichier vide")
    if len(data) > MAX_BYTES:
        raise ValueError("Photo trop lourde (8 Mo max.)")
    if Image is not None:
        try:
            im = Image.open(io.BytesIO(data))
            im = ImageOps.exif_transpose(im).convert("RGB")
            im = ImageOps.fit(im, (SIZE, SIZE), Image.LANCZOS)      # carré centré (avatar rond)
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=85, optimize=True)
            data = buf.getvalue()
        except Exception:
            raise ValueError("Ce fichier n'est pas une image (JPEG, PNG…)")
    elif not (data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Format accepté : JPEG ou PNG")
    os.makedirs(PHOTO_DIR, exist_ok=True)
    p = path_for(mac)
    tmp = p + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, p)
    v = int(time.time())
    os.utime(p, (v, v))
    return v


def delete(mac):
    try:
        os.remove(path_for(mac))
        return True
    except FileNotFoundError:
        return False


def version(mac):
    try:
        return int(os.path.getmtime(path_for(mac)))
    except (OSError, ValueError):
        return None


def versions():
    """{ "30:32:42:32:64:01": 1790931999, … } pour toutes les photos."""
    out = {}
    try:
        names = os.listdir(PHOTO_DIR)
    except OSError:
        return out
    for n in names:
        m = re.fullmatch(r"([0-9A-F]{12})\.jpg", n)
        if m:
            h = m.group(1)
            try:
                out[":".join(h[i:i + 2] for i in range(0, 12, 2))] = int(os.path.getmtime(os.path.join(PHOTO_DIR, n)))
            except OSError:
                pass
    return out
