# Résumé projet « Gateway RHM » (ex-QRing) — état au 28/09/2026

## 1. Architecture
- **Bague** COLMI R10 (MAC `30:32:42:32:64:01`, fw `RT03CR_1.00.01_250104`), SDK QRing 1.0.0.7 (`qring_sdk_1.0.0.7.aar`).
- **App Android « Gateway RHM »** (Kotlin / Jetpack Compose, TV + téléphone), package `com.eis.qringmqtt` : passerelle BLE ↔ MQTT, service au démarrage (onboot).
- **Broker Mosquitto** `51.83.40.138:1883`. Topics : `eis/colmi/<MAC12>/{status,cmd,hr,spo2,…}` et `eis/colmi/gateway/<nom>/…` (statut retenu + LWT). Le nom du gateway est fixé à la connexion MQTT (renommer = redémarrer l'app/TV).
- **QRing Admin** (Flask, pm2, port 5055) : écrit dans PostgreSQL `smart_ring` (gateways, rings, ring_current_state, ring_measurements, ring_events), sert aussi la **Web App Telegram** (`/webapp/ring/<mac>`, derrière `https://www.itigroups.biz:5000`).
- **Bot Telegram** (`telegram_bot.py`, pm2) : autonome, parle directement à MQTT (reqId `tg-…`), lit la base seulement pour les droits et l'historique. Admin = reqId `adm-`, Web App = `web-`.
- Un seul `.env` pour admin + bot (voir `.env.example`). Variables tolérantes (`60,` accepté).

## 2. Dossiers sur le PC (Windows)
- Racine : `C:\Users\HP\QRing_Android_SDK_1.0.0.7\`
- App Android : `QRingMqtt\` (compilée dans Android Studio) — sauvegarde avant les modifs du 28/09 : `QRingMqtt_28_09\`
- Serveur : `QRingAdmin\` (`app.py`, `dbq.py`, `telegram_bot.py`, `templates/index.html`, `templates/webapp.html`, `README.md`, `.env.example`, `requirements.txt`)
- Ancien code DANY `colmi_dany_complete` : **ne pas modifier**.

## 3. Règle « État / Status » de la bague (commune app, bot, Web App)
- Hors portée / TV hors ligne : affiché tout de suite, rien n'est lancé.
- Sinon une mesure HR est lancée : **15 s sans problème = bague portée** (la mesure continue) ; « retirée » si la bague le signale.
- Une seule mesure à la fois par bague ; même mesure demandée par 2 personnes = résultat partagé ; mesure différente = refusée (« mesure en cours »).
- Chaque résultat affiche heure + durée de mesure.

## 4. App Android — ce qui a été fait le 28/09 (écrit sur le PC, vérifié md5)
Fichiers modifiés : `App.kt`, `data/I18n.kt`, `data/Models.kt`, `ble/RingManager.kt`, `ui/StatusCheck.kt` (nouveau), `ui/HomeScreen.kt`, `ui/MainActivity.kt`, `ui/SettingsScreen.kt`, `AndroidManifest.xml`, `res/values/strings.xml`, `res/values/colors.xml`, + icônes `mipmap-*/ic_rhm*.png`, `mipmap-anydpi-v26/ic_rhm*.xml`, `drawable-nodpi/rhm_logo.png`, `drawable-xhdpi/rhm_banner.png`.

- **Nom / logo** : « Gateway RHM » partout, logo RHM en haut du menu, icône d'app Android + bannière Android TV.
- **Menu TV** : Accueil · État bague (sans clignotement, « … » pendant la vérification) · Activité · Historique · Journal 🔒 · Scanner 🔒 (logo Bluetooth) · Réglages 🔒. En bas : carte bague sur 3 lignes (« ● Bague portée » / « COLMI R10_6401 » / « vérifiée à 12:51 », date si pas aujourd'hui) et carte « ● Broker MQTT : En ligne » sur une ligne.
- **Accueil TV (sans défilement)** : bandeau d'infos bague en première ligne (batterie, nom, MAC, modèle, fw, « 🔋 lue à », état en pastille), puis modules (max 100 dp de haut, 4 par ligne) dans l'ordre HR · SpO2 · Température · (Tension) · HRV / Batterie · Pas · Stress · Sédentarité / Entraînements · Sommeil, puis « Tout mesurer » et « Actualiser l'état de la bague » (clignote quand cliquable). Téléphone : même ordre, grille qui défile.
- **État affiché** : 🔵 Bague connectée (à l'ouverture) · 🟢 portée · 🟡 retirée · 🔴 hors portée · Connexion… · Aucune bague.
- **Actualiser / État bague** : pas de compte à rebours. Sans mesure en cours → lit la batterie puis lance HR (règle des 15 s). Si une mesure tourne → popup « Mesure en cours, veuillez patienter », bouton « En attente de la fin de la mesure… », puis vérification lancée automatiquement à la fin.
- **Popups** (TV + téléphone, focus télécommande) : 🔴 « Votre bague s'est éloignée » (clignote, après 10 s de coupure, reconnexion auto, bouton OK) · 🟡 « Oups, la bague n'est pas portée » (Réessayer / Fermer, 30 s, aussi pour mesures à distance) · 🟢 « Content de vous revoir ! On vérifie qu'elle est bien à votre doigt ? » (Oui, vérifier / Plus tard, 30 s) · 🔵 « Mesure en cours ». Plus de plein écran TV pour la vérification ni pour « retirée / hors portée ».
- **Origine sous les valeurs** : « via TV » (téléphone : « via téléphone ») au lieu de « manuel », « à distance » au lieu de « MQTT » (codes JSON `manual`/`mqtt`/`auto` inchangés).
- **Carte Batterie** : « il y a X min » au lieu de « lue à ».
- Accéléromètre : abandonné pour l'instant.

## 5. À faire / idées en attente
- Compiler et tester la dernière version sur la TV (Build → Rebuild Project), vérifier que tout tient sur l'écran d'accueil.
- Option : retirer Sédentarité / Entraînements / Sommeil de l'accueil si inutiles.
- Option : « il y a X min » aussi dans le bandeau (actuellement « 🔋 lue à »).
- Option : afficher « à distance · Telegram / Admin / Web App » (le reqId permet de le savoir).
- Reconnexion MQTT automatique après renommage du gateway (aujourd'hui il faut redémarrer).
- Serveur : renseigner `TELEGRAM_ADMIN_IDS`, `QRING_SECRET_KEY`, `TELEGRAM_ALERTS_ENABLED=1` dans le `.env`.

## 6. Règles de travail avec l'assistant
- Discuter et montrer une maquette **avant** de coder ; attendre la validation.
- Livrer des fichiers complets, syntaxe vérifiée ; vérifier par md5 après écriture sur le PC ; ne jamais écraser une modification manuelle sans comparer.
- Ne jamais afficher les secrets du `.env` (mots de passe, token Telegram) ; ne jamais écrire dans la base de production ; utiliser seulement le schéma de `smart_ring_full.sql`, pas ses données.
- L'APK ne peut pas être compilé côté assistant : l'utilisateur compile dans Android Studio et envoie des captures.
