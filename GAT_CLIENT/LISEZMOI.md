# GAT_CLIENT — client Flutter (carte de présence + mesure HR)

Reprend le fonctionnement de la page « Live Ring Map » : écoute le multicast UDP des gateways,
affiche la zone probable de la bague, et lance une mesure HR sur la gateway au meilleur signal.

Canaux (identiques à GAT_ANDROID et à la page web) :
- 239.10.10.10:5010 : présence (OBS), en réception
- 239.10.10.12:5012 : commande de mesure (GATT_CMD), en émission
- 239.10.10.13:5013 : statut et résultat (GATT_STATUS, GATT_RESULT), en réception

Le téléphone doit être sur le même réseau local (Wi-Fi) que les gateways.

## Mise en route (une seule fois)

Dans le dossier GAT_CLIENT, dans un terminal :

    flutter create --org com.eis --project-name gat_client .
    flutter pub get

Si Flutter a remplacé `pubspec.yaml` ou `lib/main.dart`, recopie ceux de `sources_backup/`.

Puis, pour Android :

1. Copier `android_patch/MainActivity.kt` vers
   `android/app/src/main/kotlin/com/eis/gat_client/MainActivity.kt` (remplacer le fichier).
2. Dans `android/app/src/main/AndroidManifest.xml`, juste avant `<application`, ajouter :

       <uses-permission android:name="android.permission.INTERNET" />
       <uses-permission android:name="android.permission.ACCESS_WIFI_STATE" />
       <uses-permission android:name="android.permission.CHANGE_WIFI_MULTICAST_STATE" />

3. Lancer : `flutter run` (ou `flutter build apk`).

iOS : le multicast demande une autorisation Apple spéciale ; utilise Android, Windows ou macOS pour les premiers essais.

## Utilisation

- La carte apparaît dès que les gateways envoient leurs observations.
- « Déplacer » (interrupteur sur la carte) : fais glisser chaque gateway à sa place sur le plan
  et touche son nom dans la liste pour renommer sa zone. Les positions sont mémorisées.
- MESURER : envoie la commande à la gateway courante (meilleur RSSI, hystérésis de 3 dB).
  Le bouton est bloqué si une autre mesure est en cours.
- Position : moyenne pondérée des gateways qui voient la bague, lissée ; cercle pointillé =
  incertitude ; « SIGNAL PERDU » après 15 s sans observation.
