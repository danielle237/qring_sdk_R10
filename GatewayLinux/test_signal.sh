#!/bin/bash
# =============================================================================
# GATEWAY RHM Linux — test du signal Bluetooth (RSSI) de la bague
# Écoute seulement (aucune connexion à la bague), pendant N secondes.
#
# Usage :
#   bash test_signal.sh                       # MAC lue dans /root/gateway_rhm/.env, 10 s
#   bash test_signal.sh 30:32:42:32:64:01     # MAC donnée
#   bash test_signal.sh 30:32:42:32:64:01 20  # MAC + durée en secondes
#
# Le service gateway-rhm est arrêté pendant le test puis relancé automatiquement.
# =============================================================================

PY=/root/.local/pipx/venvs/colmi-r02-client/bin/python
ENV_FILE=/root/gateway_rhm/.env
SERVICE=gateway-rhm

MAC="$1"
SECONDS_SCAN="${2:-10}"

# MAC depuis le .env si non donnée
if [ -z "$MAC" ] && [ -f "$ENV_FILE" ]; then
    MAC=$(grep -E '^RING_MAC=' "$ENV_FILE" | head -1 | cut -d= -f2 | tr -d ' "\r')
fi
if [ -z "$MAC" ]; then
    echo "MAC de la bague manquante : bash test_signal.sh 30:32:42:32:64:01"
    exit 1
fi
if [ ! -x "$PY" ]; then
    echo "Python de colmi_r02_client introuvable ($PY)"
    echo "Vérifiez avec : head -1 /root/.local/bin/colmi_r02_client"
    exit 1
fi

# Service arrêté pendant le test (un seul programme sur le Bluetooth à la fois)
WAS_ACTIVE=0
if systemctl is-active --quiet "$SERVICE"; then
    WAS_ACTIVE=1
    echo "Arrêt de $SERVICE pendant le test…"
    systemctl stop "$SERVICE"
    sleep 2
fi
bluetoothctl power on >/dev/null 2>&1

echo "Écoute de la bague $MAC pendant $SECONDS_SCAN s…"
echo "----------------------------------------"
"$PY" - "$MAC" "$SECONDS_SCAN" <<'EOF'
import asyncio, sys, statistics, time
from bleak import BleakScanner

mac = sys.argv[1].upper()
duration = float(sys.argv[2])
vals = []

def cb(dev, adv):
    if dev.address.upper() == mac:
        vals.append(adv.rssi)
        print(f"{time.strftime('%H:%M:%S')}  {dev.name or '?'}  RSSI {adv.rssi} dBm", flush=True)

async def main():
    async with BleakScanner(cb):
        await asyncio.sleep(duration)

try:
    asyncio.run(main())
except Exception as e:
    print(f"Erreur Bluetooth : {e}")

print("-" * 40)
if vals:
    med = statistics.median(vals)
    if med >= -60:
        zone = "très proche (même pièce, < 2 m)"
    elif med >= -75:
        zone = "proche (même pièce)"
    elif med >= -90:
        zone = "loin (pièce voisine / à travers un mur)"
    else:
        zone = "très loin (limite)"
    print(f"{len(vals)} signaux · médiane {med:.0f} dBm · min {min(vals)} · max {max(vals)}  →  {zone}")
else:
    print("Bague non entendue (trop loin, connectée ailleurs — app QRing / TV —, ou Bluetooth éteint)")
EOF

# Relance du service
if [ "$WAS_ACTIVE" = "1" ]; then
    echo "Relance de $SERVICE…"
    systemctl start "$SERVICE"
fi
