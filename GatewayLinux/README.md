# GATEWAY RHM — version Linux (DietPi / Raspberry Pi)

Remplace la TV Android : écoute les commandes MQTT (admin, Client RHM) et lance
`colmi_r02_client` pour mesurer sur la bague. Mêmes topics et même format que la TV.

| Commande MQTT | colmi_r02_client |
|---|---|
| hr | get-real-time heart-rate |
| spo2 | get-real-time spo2 |
| hrv | get-real-time hrv |
| stress | get-real-time pressure |
| all | les 4 à la suite |
| battery / info | info |
| steps | get-steps (total du jour + pas par heure) |
| sedentary | get-steps → tranches de 15 min avec moins de 30 pas, entre 8 h et 21 h |
| temp, sleep… | non supporté (réponse `not_supported`) |

## Statut et « Actualiser »
- Type : `GATEWAY_TYPE=linux` dans `.env`, envoyé dans le statut (`gatewayType`) ; la TV Android ne l'envoie pas → le serveur la traite en « android ».
- Statut (toutes les 60 s, retenu) : Gateway **en ligne** (connectée à Internet / MQTT) + **bague associée** (`RING_MAC`).
  Pas de connexion Bluetooth périodique (`RING_CHECK_SECONDS=0`).
- « Actualiser » (Client RHM) : le serveur envoie `battery` puis **`hr`** → `get-real-time heart-rate`,
  la valeur (bpm) revient dans le Client. Autorisé même si la bague était marquée hors portée (elle se revérifie).
  Si la bague n'est pas portée → « retirée » ; injoignable plusieurs fois → « hors portée ».

## IP WAN et redémarrage à distance
- IP publique (WAN) lue sur `api.ipify.org` (au démarrage puis toutes les 30 min) et envoyée dans le statut, comme la TV.
- Page Gateways de l'admin : « 📶 Redémarrer Bluetooth » (`btrestart` : `systemctl restart bluetooth`, puis test de la bague avec `info`),
  « 🔄 Service » (`restart` : `systemctl restart gateway-rhm`, nom modifiable avec `SERVICE_NAME`)
  et « ⏻ Redémarrer machine » (`reboot` : `systemctl reboot`). Désactivables avec `ALLOW_REMOTE_BT_RESTART=0`, `ALLOW_REMOTE_RESTART=0` / `ALLOW_REMOTE_REBOOT=0`.
  Le service doit tourner avec systemd (`gateway-rhm.service`, `Restart=always`) pour revenir tout seul.

## Même bague sur une TV Android : priorité Android
- La gateway écoute aussi `eis/colmi/<MAC>/status`. Si une TV Android annonce cette bague (associée, en ligne),
  la gateway Linux passe **en veille** : plus de statut sur le topic de la bague, commandes de mesure ignorées
  (la TV répond seule). Dans l'admin : « En veille (priorité Android) · Bague prise par 📺 <TV> ».
- Dès que la TV libère la bague (dissociée, hors ligne, ou plus de statut depuis `OWNER_TIMEOUT_SECONDS`=150 s),
  la gateway Linux la reprend toute seule.
- L'admin signale « ⚠ N GATEWAYS » si deux gateways gardent la même bague plus de 90 s.

## Plusieurs Gateway Linux : localisation par le serveur (v3)
- Plus de roaming automatique entre gateways (`ROAMING` ignoré).
- **⟳ Actualiser** (Client RHM) : `client_api` demande le test de portée **à tour de rôle** à chaque gateway Linux
  de la bague → chacune lance `test_reachable_v1.py --mac … --gateway <nom> --json` (écoute seule, aucune connexion).
  La gateway au **meilleur RSSI** = position de la bague, publiée sur `eis/colmi/<MAC>/location` (retenu).
- **Mesures** : envoyées directement à la gateway au meilleur RSSI (`"gateway": "<nom>"` dans la commande) ;
  localisation refaite si elle a plus de `LOCATION_TTL_SECONDS` (120 s) ; si cette gateway n'arrive pas à se
  connecter, la suivante du classement essaie (un seul essai Bluetooth quand il y a un relais).
- Commandes sans destinataire (admin, bot) : exécutées par la gateway où la bague est localisée.
- Seule la gateway localisée publie l'état de la bague ; les autres : « En veille · bague sur 🐧 <nom> ».
- Bluetooth : `systemctl restart bluetooth` après chaque mesure réussie et à l'arrêt ; pas après un test de portée.
- **Mesures HR / SpO2 / all** : `wiss_test_04_fast_one_connection.py --mac … --gateway <nom> --json --no-mqtt`
  (une connexion : batterie + HR + SpO2 ; le script redémarre lui-même le Bluetooth). Les valeurs sont publiées
  par la gateway sur les topics habituels (hr, spo2, battery). HRV, stress, pas, batterie seule : colmi_r02_client.
- **Mesure demandée pendant un test de portée** : le test est arrêté, `systemctl restart bluetooth`, puis la mesure.
- Script de portée : `REACH_SCRIPT` (défaut `/root/colmi_wiss/test_reachable_v1.py`), `REACH_PYTHON`
  (défaut python3.14), `REACH_WINDOW` (5 s).

## Multi-bagues et zones (v3.2) — `gateway_multi.py`
- Dans l'admin : chaque gateway reçoit un **nom de pièce** (Chambre 12, Salon…) et chaque bague
  **1 zone principale + 0 à 5 zones secondaires** (fiche de la bague → « Zones de la bague »).
- L'admin publie la liste des bagues de chaque gateway (retenue) : `eis/colmi/gateway/<nom>/rings`.
- Sur le Pi, `gateway_multi.py` (le service) :
  - lance **une instance de `gateway_linux.py` par bague** (mêmes mesures, mêmes scripts qu'avant) ;
  - fait l'**écoute passive en continu** (`scan_rings.py`, aucune connexion) et publie toutes les ~5 s
    `eis/colmi/gateway/<nom>/presence` (bagues entendues + RSSI) ;
  - garantit **une seule connexion Bluetooth à la fois** (verrou `/run/gateway-rhm/bt.lock`) : une mesure
    interrompt l'écoute tout de suite ; deux mesures sur le même Pi se font l'une après l'autre ;
  - publie le statut de la gateway et gère les boutons de l'admin (Bluetooth, service, reboot).
- `client_api` localise chaque bague **en temps réel** : meilleur RSSI entendu il y a ≤ 15 s, zone principale
  favorisée (+5 dB), « non détectée » après 2 écoutes complètes sans elle (~10 s) ou 15 s.
- Mesure : envoyée au Pi au meilleur RSSI ; s'il est **occupé avec une autre bague**, à une autre zone qui
  l'entend bien (≥ −90 dBm) — sinon elle attend son tour.
- « Actualiser » (portée) : réponse immédiate d'après l'écoute passive.
- Aucune zone choisie pour cette gateway : elle utilise `RING_MAC` du `.env` (comme avant).
- Revenir à l'ancien mode une bague : `ExecStart=… gateway_linux.py` dans le service.

## Installation
```bash
pip install paho-mqtt            # (python3 -m pip install --break-system-packages paho-mqtt sur DietPi récent)
mkdir -p /root/gateway_rhm && cd /root/gateway_rhm
# copier gateway_multi.py, gateway_linux.py, scan_rings.py, .env.example, gateway-rhm.service ici
cp .env.example .env && nano .env        # MQTT_HOST, MQTT_USER, MQTT_PASS, RING_MAC…
python3 gateway_multi.py                 # test à la main (Ctrl+C pour arrêter)
cp gateway-rhm.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now gateway-rhm
journalctl -u gateway-rhm -f             # voir les logs
```
Important : une seule gateway doit parler à la bague à la fois (couper la TV Android pour cette bague).
