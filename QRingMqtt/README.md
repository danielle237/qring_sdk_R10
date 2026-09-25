# QRing MQTT

Application Android (téléphone + Android TV) qui relie une bague QRing / Colmi à un broker MQTT.
Un service en tâche de fond garde la bague et le broker connectés : les mesures se lancent
par MQTT même si l'application est fermée, et le service démarre avec l'appareil.

## Compiler

1. Ouvrir le dossier `QRingMqtt` dans Android Studio.
2. Laisser Gradle synchroniser (Kotlin 1.9.24, AGP 8.6.0, Gradle 8.10.2).
3. Run ▶ sur le téléphone ou la box TV.

Le SDK du fabricant est dans `app/libs/qring_sdk_1.0.0.7.aar`.

## Premier lancement

L'app demande une seule fois :
1. Bluetooth + localisation + notifications (obligatoire)
2. L'exclusion de l'optimisation de batterie (arrière-plan)
3. Le démarrage automatique (Xiaomi, Huawei, Oppo, Vivo… uniquement)

Puis **Accueil → Scanner** pour associer la bague.

Code PIN des écrans Journal et Réglages : **12345** (modifiable dans Réglages).

## Topics

`{prefixe}` = `eis/colmi` par défaut, `{MAC}` = MAC de la bague sans « : » (ex. `C4A15F22A4F1`).

| Topic | Sens | Contenu |
|---|---|---|
| `eis/colmi/{MAC}/cmd` | serveur → app | commande |
| `eis/colmi/{MAC}/status` | app → serveur (retenu) | statut chaque minute + Last Will |
| `eis/colmi/{MAC}/{type}` | app → serveur | résultat (`hr`, `spo2`, `temp`…) |
| `eis/colmi/gateway/{nom-TV}/cmd` | serveur → app | commandes du gateway (toujours écouté) |
| `eis/colmi/gateway/{nom-TV}/status` | app → serveur (retenu) | statut du gateway (chaque minute) |
| `eis/colmi/gateway/{nom-TV}/bind`, `/unbind`, `/scan`, `/lang` | app → serveur | réponses du gateway |

`{nom-TV}` = nom de la TV (Paramètres Android → À propos → Nom de l'appareil), espaces remplacés
par `-`. Modifiable dans Réglages. **Doit être unique.**

## Commandes

Envoyer sur `…/cmd` du JSON `{"cmd":"spo2","reqId":"a7"}` ou simplement le texte `spo2`.
`reqId` est facultatif et renvoyé tel quel. `day` (0 = aujourd'hui, 1 = hier… jusqu'à 6) pour les synchronisations.

| Commande | Réponse |
|---|---|
| `hr` | `value` (bpm), `rri` (ms) |
| `spo2` | `value` (%) |
| `temp` | `value` (°C) |
| `bp` | `sbp`, `dbp` (mmHg) |
| `hrv` | `value` (ms) |
| `stress` | `value` (score) |
| `all` | `hr`, `rri`, `spo2`, `hrv`, `stress`, `temp`, `sbp`, `dbp` |
| `steps` | `steps`, `distance` (m), `calories`, `activeSeconds`, `hourly[24]` |
| `sleep` | `totalSeconds`, `deepSeconds`, `lightSeconds`, `remSeconds`, `awakeSeconds`, `phases`/`sequence` |
| `sedentary` | `stillMinutes`, `sedentaryMinutes`, `movingMinutes`, `sequence` |
| `workouts` | `count`, `workouts[]` |
| `history` | séries `hr`, `stress`, `hrv`, `spo2`, `temp` : `[{minute, value}]` |
| `battery` | `value` (%), `charging` |
| `info` | nom, firmware, matériel, batterie, fonctions supportées |
| `ping` | republie le statut |
| `cancel` | annule la mesure en cours |

Commandes du gateway (sur `eis/colmi/gateway/{nom-TV}/cmd`) :

| Commande | Rôle / réponse |
|---|---|
| `{"cmd":"bind","mac":"C4:A1:5F:22:A4:F1"}` | cherche la bague (15 s max) et l'associe → `status: searching` puis `ok` ou `not_found` / `bluetooth_off` / `busy` |
| `{"cmd":"unbind"}` | dissocie la bague (l'ancienne bague publie `online:false`, `ring:"unbound"`) |
| `{"cmd":"scan"}` | liste des bagues à proximité (13 s) → `rings:[{name,mac,rssi}]` |
| `{"cmd":"lang","value":"ar"}` | langue de l'app : `fr`, `en`, `ar` (gardée en mémoire) |
| `ping` | republie le statut |

Délais maximum d'une mesure : cœur 60 s, SpO2 90 s (autres 60 s, `all` 90 s).
Une seule tentative : pas de relance automatique. Le résultat s'affiche dès que la bague s'arrête.
Si la bague répond sans signal → `ring_removed` et « Veuillez porter la bague » à l'écran.

Exemples :

```bash
mosquitto_pub -h 51.83.40.138 -p 1883 -u tvclient -P '***' -t eis/colmi/C4A15F22A4F1/cmd -m '{"cmd":"spo2","reqId":"a7"}'
mosquitto_sub -h 51.83.40.138 -p 1883 -u tvclient -P '***' -t 'eis/colmi/#' -v
```

Pendant une mesure : `{"reqId":"a7","type":"spo2","status":"measuring",…}`
Résultat :
```json
{"reqId":"a7","type":"spo2","status":"ok","value":97,"unit":"%","source":"mqtt",
 "ringMac":"C4:A1:5F:22:A4:F1","ringModel":"R06","gateway":"TV-salon","ts":1727184612}
```
Erreur :
```json
{"reqId":"a7","type":"spo2","status":"error","error":"ring_disconnected", …}
```
Codes d'erreur : `ring_disconnected`, `ring_removed`, `timeout`, `measure_failed`, `not_supported`,
`invalid_value`, `cancelled`, `no_data`, `unknown_command`, `not_found`, `bluetooth_off`, `busy`, `bad_request`.

## Statut (chaque minute, message retenu)

```json
{"online":true,"ring":"connected","ringMac":"C4:A1:5F:22:A4:F1","ringModel":"R06",
 "ringName":"R06_A4F1","firmware":"2.1.8","battery":82,"charging":false,"worn":true,
 "measuring":null,"gateway":"TV-Chambre-104","deviceName":"TV Chambre 104",
 "lanIp":"192.168.1.25","wanIp":"41.x.x.x","lang":"fr","appVersion":"1.0.0","ts":1727184612}
```
`ring` : `connected`, `connecting`, `disconnected`, `bluetooth_off`, `no_ring` (`unbound` après dissociation).
`worn` : `true` après une mesure réussie, `false` si la bague a été détectée retirée, `null` inconnu.
`wanIp` : IP publique (api.ipify.org, rafraîchie toutes les 30 min et à chaque changement de réseau).
Si le gateway disparaît (réseau, courant), le broker publie `{"online":false,…}` (Last Will).
La batterie est lue à l'ouverture de l'app (ou avec la commande `battery`).

## Langues

Français, anglais, arabe (écran de droite à gauche). Réglages → Langue, ou MQTT `{"cmd":"lang","value":"en"}`.

## Organisation du code

```
app/src/main/java/com/eis/qringmqtt/
  App.kt                  initialisation
  ble/RingManager.kt      connexion bague, reconnexion, scan, batterie, infos
  ble/Measurer.kt         mesures manuelles (cœur, SpO2, temp, tension, HRV, stress, tout)
  ble/Syncer.kt           pas, sommeil, sédentarité, entraînements, historique
  mqtt/MqttManager.kt     broker, Last Will, file hors ligne
  service/RingService.kt  service en tâche de fond + notification
  service/CommandProcessor.kt  file des commandes, JSON
  service/BootReceiver.kt démarrage automatique
  data/                   état partagé, réglages, historique local
  ui/                     écrans Compose (téléphone + TV)
```

## À vérifier sur la vraie bague

- Échelle de la température (conversion automatique dans `Measurer.tempC`).
- Unités du sommeil (minutes ou secondes, détection automatique dans l'interface).
- Stress / HRV de l'historique : valeurs brutes de la bague.
