# QRingClient — app téléphone (Flutter)

Remplace la Web App Telegram : identifiant + mot de passe, bagues affectées par l'administrateur,
état en temps réel (Mosquitto → serveur → app), mesures, « Actualiser l'état », historique, alertes et
notifications Firebase.

L'app parle uniquement au service **qring-client-api** (`QRingAdmin/client_api.py`), jamais directement
à Mosquitto. Ce service est indépendant de QRing Admin : l'app marche même si l'admin (Flask) est arrêté.

## 1. Compléter le projet (une seule fois)

Le dossier `QRingClient\` contient déjà le code (`pubspec.yaml`, `lib\`, `assets\`, `AndroidManifest.xml`).
Il manque les fichiers Android générés par Flutter (Gradle…). Dans `QRingClient\` :

```bash
flutter create --org com.eis --project-name qring_client --platforms android .
```

`flutter create` ajoute seulement les fichiers manquants : il ne remplace pas le code fourni.

**Identifiant de l'app : `com.eis.client_RHM`.** Flutter n'accepte pas de majuscules dans le nom du projet,
donc après `flutter create`, ouvrir `android\app\build.gradle.kts` (ou `build.gradle`) et remplacer la ligne
`applicationId` par :

```kotlin
applicationId = "com.eis.client_RHM"      // build.gradle.kts
```
```groovy
applicationId "com.eis.client_RHM"        // build.gradle (ancien format)
```

Ne pas toucher à `namespace` (il reste `com.eis.qring_client`, c'est normal).
Vérifier ensuite que `android\app\src\main\AndroidManifest.xml` contient bien `QRingClient` et
`POST_NOTIFICATIONS` (sinon recopier celui fourni).

```bash
flutter pub get
dart run flutter_launcher_icons      # icône RHM
flutter run                          # téléphone branché en USB (débogage activé)
flutter build apk --release          # APK : build\app\outputs\flutter-apk\app-release.apk
```

Si `flutter pub get` signale des versions trop anciennes : `flutter pub upgrade --major-versions`.

## 2. Adresse du serveur

Par défaut : `https://www.itigroups.biz:5060` (modifiable sur l'écran de connexion,
« Paramètres du serveur »). À changer dans `lib/api.dart` (`kDefaultServer`) si besoin.

## 3. Notifications (Firebase)

1. console.firebase.google.com → **Créer un projet** « QRingClient ».
2. **Ajouter une app Android**, nom de package `com.eis.client_RHM` (majuscules comprises) → télécharger `google-services.json`.
3. Ouvrir `google-services.json` et recopier 4 valeurs dans `lib/firebase_config.dart` :
   `apiKey`, `appId`, `messagingSenderId`, `projectId` (l'emplacement de chaque valeur est indiqué dans le fichier).
4. Côté serveur : Paramètres du projet → **Comptes de service** → **Générer une nouvelle clé privée** →
   fichier JSON à poser à côté de `client_api.py`, puis dans le `.env` :
   `FCM_SERVICE_ACCOUNT_FILE=nom-du-fichier.json` et redémarrer `qring-client-api`.

Sans ces réglages, l'app fonctionne ; les alertes s'affichent seulement quand l'app est ouverte.

## 4. Écrans

- **Connexion** : identifiant, mot de passe, « rester connecté », FR / EN / العربية.
- **Mes bagues** : état en direct (🟢 portée · 🟡 retirée · 🔴 hors portée · ⚫ TV hors ligne), batterie,
  dernière valeur, interrupteur « Alertes : toutes les bagues ».
- **Une bague** : bandeau, interrupteur « Alertes pour cette bague », dernières mesures (heure, durée,
  via TV / à distance), boutons HR · SpO2 · T° · HRV · Stress · Pas (selon les droits),
  « Actualiser l'état » (batterie + HR : 15 s sans problème = portée ; si une mesure tourne :
  « veuillez patienter », puis la vérification démarre toute seule), Historique.
- **Historique** : 24 h / 7 j / 30 j, courbe, moyenne / min / max, liste.
- **Alertes** : retirée, hors portée, TV hors ligne, batterie faible, rétablie.
- **Profil** : langue, « Recevoir les alertes », changer le mot de passe, se déconnecter.
