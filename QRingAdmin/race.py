"""
Roaming « course » des Gateway RHM Linux (ROAMING=race) — logique commune à app.py et client_api.py.

Toutes les gateways Linux d'une bague reçoivent la commande ; la première qui se connecte mesure.
Les autres répondent « ring_disconnected » (course perdue) avec "roaming": "race".
Règle : une valeur (ok) gagne toujours ; une erreur de course n'est affichée que si TOUTES les
gateways en ligne de la bague ont échoué, ou après RACE_TIMEOUT secondes sans résultat.
"""
import time

RACE_TIMEOUT = 45
LOSS_ERRORS = ("ring_disconnected", "timeout")


def candidates(gateways, mac):
    """Nombre de Gateway RHM en ligne qui annoncent cette bague (au moins 1)."""
    mac = (mac or "").upper()
    seen = set()
    for g in gateways.values():
        if g.get("online") and (g.get("ringMac") or "").upper() == mac:
            seen.add(id(g))
    return max(1, len(seen))


def hold_error(r, sub, p, needed):
    """True = erreur de course à ne pas afficher (encore) : on attend les autres gateways."""
    if p.get("roaming") != "race" or p.get("status") != "error" or p.get("error") not in LOSS_ERRORS:
        return False
    req = p.get("reqId") or ""
    pnd = r["pending"].get(sub)
    if not pnd or (pnd.get("reqId") and req and pnd.get("reqId") != req):
        # Résultat déjà arrivé (une autre gateway a gagné) : cette défaite arrive en retard → ignorée
        return True
    race = r.setdefault("race", {})
    e = race.setdefault(req, {"sub": sub, "fails": [], "ts": time.time(), "last": None})
    gw = p.get("gateway") or "?"
    if gw not in e["fails"]:
        e["fails"].append(gw)
    e["last"] = p
    if len(e["fails"]) >= needed:
        race.pop(req, None)
        return False          # toutes ont échoué : erreur affichée
    return True


def settle(r, p):
    """Un résultat définitif est arrivé pour ce reqId : la course est terminée."""
    req = p.get("reqId")
    if req and r.get("race"):
        r["race"].pop(req, None)


def is_duplicate_ok(r, sub, p):
    """Deuxième « ok » pour le même reqId (deux gateways ont mesuré l'une après l'autre) → ignoré."""
    req = p.get("reqId")
    if not req or p.get("status") != "ok" or p.get("roaming") != "race":
        return False
    pnd = r["pending"].get(sub)
    if pnd and pnd.get("reqId") == req:
        return False
    last = r["values"].get(sub) or {}
    return last.get("reqId") == req


def expired(r):
    """Courses sans résultat depuis RACE_TIMEOUT : [(sub, dernier message d'erreur)] à afficher."""
    out = []
    race = r.get("race") or {}
    t = time.time()
    for req, e in list(race.items()):
        if t - e["ts"] >= RACE_TIMEOUT:
            race.pop(req, None)
            pnd = r["pending"].get(e["sub"])
            if pnd and (not pnd.get("reqId") or pnd.get("reqId") == req) and e["last"]:
                out.append((e["sub"], e["last"]))
    return out
