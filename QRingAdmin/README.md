# QRing Admin (Flask) — version PostgreSQL / Telegram

Tableau de bord web des bagues QRing. Les gateways sont les TV / téléphones Android
(application QRing MQTT) — la Pi400 n'est plus utilisée.

- **Une ligne par bague (MAC)**, mise à jour en direct
- **Mesures à distance** : début → en cours → résultat / bague retirée / hors portée.
  **Une seule mesure à la fois par bague** : la même mesure déjà lancée est partagée,
  une mesure différente est refusée (« mesure en cours ») pour ne pas fausser le résultat.
- **PostgreSQL `smart_ring` (DANY)** : chaque statut et résultat reçu par MQTT est écrit dans
  `gateways`, `rings`, `ring_current_state`, `ring_measurements`, `ring_events`.
  Le bot Telegram et l'ancien admin lisent donc les mêmes données.
- **Accès Telegram** (bouton ✈ sur chaque bague) : une bague peut être affectée à plusieurs
  utilisateurs ; droits oui/non (voir, historique, mesures, alertes, admin) et
  **mesures autorisées** : toutes (droit général) ou au choix (HR, SpO₂, T°, tension, HRV, stress).
  Chaque affectation / retrait envoie un message à l'`id_telegram` de l'utilisateur.
- **Appariements QR** : approuver / refuser les demandes (message Telegram envoyé)
- **Utilisateurs Telegram** : suivi, bagues affectées, Web App ouverte, activer / désactiver
- **Sessions Web App** : qui a ouvert quelle bague, actives en ce moment, durées
- Indicateur **PostgreSQL connecté / non connecté** (cliquer pour les détails)

L'ancien code `colmi_dany_complete` n'est pas modifié.

## Installation

```bash
cd QRingAdmin
python -m venv venv
source venv/bin/activate          # Windows : venv\Scripts\activate
pip install -r requirements.txt
```

Une seule fois, sur la base (ajoute la colonne des droits par mesure, sans rien supprimer) :

```bash
psql -h 127.0.0.1 -U iti -d smart_ring -f qring_admin_migration.sql
```

Sans cette migration, l'admin fonctionne : « Lancer des mesures » autorise alors toutes les mesures.

## Configuration : le même `.env` que DANY

L'admin lit, dans l'ordre : `QRING_ENV_FILE`, puis `QRingAdmin/.env`, puis le `.env` du dossier parent.
Le plus simple : pointer vers le `.env` existant de DANY.

| Variable | Défaut | Rôle |
|---|---|---|
| `MQTT_HOST` / `MQTT_PORT` | 51.83.40.138 / 1883 | broker |
| `MQTT_USER` / `MQTT_PASSWORD` (ou `MQTT_PASS`) | — | identifiants broker |
| `MQTT_PREFIX` (ou `MQTT_TOPIC`) | eis/colmi | préfixe des topics |
| `DB_HOST` `DB_PORT` `DB_NAME` `DB_USER` `DB_PASSWORD` | 127.0.0.1 / 5432 / smart_ring / iti | PostgreSQL |
| `DB_ENABLED` | true | `false` = admin sans base |
| `TELEGRAM_BOT_TOKEN` | — | envoi des messages d'affectation |
| `TELEGRAM_WEBAPP_ACTIVE_SECONDS` | 60 | session Web App « active » si heartbeat plus récent |
| `QRING_ADMIN_PASSWORD` (ou `ADMIN_PASSWORD`) | admin | mot de passe de la page — **à définir** |
| `QRING_SECRET_KEY` (ou `SECRET_KEY`) | aléatoire | clé des sessions |
| `QRING_ADMIN_PORT` | 5055 | port web (l'ancien admin reste sur 5001) |
| `QRING_OFFLINE_AFTER` | 150 | secondes sans statut avant « hors ligne » |
| `TELEGRAM_WEAR_CHECK_SECONDS` | 20 | bot : durée du test de port (bouton État) |
| `TELEGRAM_WEAR_REUSE_SECONDS` | 120 | bot : réutilisation d'un port vérifié |
| `TELEGRAM_RING_WATCH_MINUTES` | 30 | bot : durée de mise à jour automatique d'un écran de bague |
| `TELEGRAM_WEBAPP_BASE_URL` | — | adresse HTTPS de QRing Admin (bouton 🌐 Web App) |
| `TELEGRAM_WEBAPP_MAX_AGE_SECONDS` | 86400 | validité de la signature Telegram de la Web App |

## Lancement

```bash
QRING_ENV_FILE=/chemin/vers/colmi_dany_complete/.env python app.py
```

Puis ouvrir **http://IP-du-serveur:5055**. Pages directes :
`/telegram/pairing`, `/telegram/users`, `/telegram/webapp`.

## Bot Telegram (`telegram_bot.py`)

Version DANY adaptée aux TV Android. L'original dans `colmi_dany_complete` n'est pas modifié.
**Le bot est autonome** : il se connecte à Mosquitto, suit l'état des bagues et publie lui-même
les mesures sur `eis/colmi/<MAC>/cmd`. Il lit seulement la base (droits, historique).
QRing Admin peut être arrêté ; c'est lui qui enregistre les mesures en base.

```bash
pm2 start telegram_bot.py --name qring-bot --interpreter ./venv/bin/python
pm2 save
pm2 logs qring-bot
```

- Une seule instance du bot par token (arrêter l'ancien bot DANY).
- Écran d'une bague : état, TV, batterie, dernières valeurs avec heure et durée ;
  boutons 🔄 État, 📊 Historique, ❤️ HR, 🫁 SpO₂, 💓 HRV, 🌡 Température, ℹ️ Infos, 🌐 Vue web
  (seuls les boutons autorisés par l'admin apparaissent).
- **🔄 État** vérifie le port : TV hors ligne / hors portée affichés tout de suite ; sinon une
  mesure HR est lancée. La bague n'est « portée » que si une vraie valeur arrive (10–15 s).
  Sans valeur après `TELEGRAM_WEAR_CHECK_SECONDS` (20 s) : « pas de signal — mal placée ou
  retirée ? », puis la réponse de la TV (retirée, ou pas de résultat). Si l'utilisateur a le
  droit HR, la valeur s'affiche. Un port confirmé est réutilisé `TELEGRAM_WEAR_REUSE_SECONDS`
  (120 s). Si une mesure tourne déjà, c'est elle qui sert de test.
- **Mise à jour automatique** : l'écran de bague affiché se réécrit tout seul quand l'état change
  (TV en ligne / hors ligne, Bluetooth, port, batterie, nouvelle valeur — même lancée par
  l'admin), pendant `TELEGRAM_RING_WATCH_MINUTES` (30 min). Un écran par conversation.
- Mesure : « demande envoyée » → « en cours (⏱ 25 s / 90 s) » → résultat avec début, fin et
  durée — ou bague retirée, hors portée, TV hors ligne, pas de résultat.
  Même mesure lancée par deux personnes : résultat partagé ; autre mesure en cours : refus.
  Le bot et QRing Admin voient les commandes l'un de l'autre (topic `cmd`).
- Historique : capteurs présents en base avec leur nombre, période, 20 lignes par page,
  ➕ Plus / ⬆️ Plus récentes.
- Le bouton LIVE (Pi400) est retiré ; QR, notifications, Web App et commandes admin inchangés.

## Web App Telegram (Mini App) — dans QRing Admin

`https://<adresse HTTPS de QRing Admin>/webapp/ring/<mac>` — ouverte par le bouton **🌐 Web App** du bot.

- Une page par bague : l'utilisateur ne voit **que la bague de cette adresse MAC**, et seulement
  s'il y est affecté (droit « voir »). Identité prouvée par la signature Telegram (`initData`) ;
  ouverte hors de Telegram ou par une personne non affectée → « Accès refusé ».
- État en direct, dernières mesures (heure + durée), résumé, boutons de mesure **selon les droits
  en base** (mêmes règles que le bot : une seule mesure à la fois), historique 24 h / 7 j / 30 j
  avec courbe. Mise à jour toutes les 3 s. Droits relus à chaque appel.
- Chaque ouverture / fermeture est enregistrée (`telegram_webapp_sessions`, `telegram_webapp_events`) :
  visible dans la page « Sessions Web App ».
- `.env` : `TELEGRAM_WEBAPP_BASE_URL=https://…` doit mener **à QRing Admin** (port 5055 derrière
  Nginx en HTTPS). Telegram exige le HTTPS. `TELEGRAM_BOT_TOKEN` sert à vérifier la signature.

## Service permanent (systemd)

```ini
[Unit]
Description=QRing Admin
After=network.target postgresql.service

[Service]
WorkingDirectory=/opt/QRingAdmin
Environment=QRING_ENV_FILE=/opt/colmi_dany_complete/.env
ExecStart=/opt/QRingAdmin/venv/bin/python app.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Derrière Nginx : `proxy_buffering off;` pour `/stream`.

## Tester sans TV ni bague

```bash
python simulate_gateway.py --host 51.83.40.138 --user tvclient --password '...' --name TV-Test-1 --mac AA:BB:CC:DD:EE:01
```

## API

| Méthode | URL | Rôle |
|---|---|---|
| GET | `/api/state` | bagues, gateways, événements, état DB |
| POST | `/api/ring/<MAC>/cmd` | `{"cmd":"spo2"}` — 409 si une autre mesure est en cours |
| POST | `/api/gateway/<nom>/cmd` | bind / unbind / scan / lang / ping |
| GET | `/api/ring/<MAC>/history?type=hr` | historique PostgreSQL |
| GET | `/api/db/status` | état PostgreSQL |
| GET / POST | `/api/telegram/ring/<MAC>` | liste / affecte ou modifie un accès |
| DELETE | `/api/telegram/ring/<MAC>/<access_id>` | retire un accès (message envoyé) |
| GET | `/api/telegram/users` | utilisateurs Telegram |
| POST | `/api/telegram/users/<id>/active` | `{"active":false}` |
| GET | `/api/telegram/pairing?status=pending` | demandes QR |
| POST | `/api/telegram/pairing/<id>/approve` \| `reject` | décision |
| GET | `/api/telegram/webapp` | sessions Web App + stats |
| GET | `/stream` | temps réel (SSE) |
