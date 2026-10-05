// Firebase (notifications quand l'app est fermée).
//
// Remplir avec les valeurs du fichier google-services.json téléchargé depuis
// console.firebase.google.com (projet QRingClient, app Android « com.eis.client_RHM ») :
//   apiKey            = client[0].api_key[0].current_key
//   appId             = client[0].client_info.mobilesdk_app_id
//   messagingSenderId = project_info.project_number
//   projectId         = project_info.project_id
//
// Laisser vide = l'app fonctionne sans notifications (les alertes restent visibles dans l'app).
class FirebaseConfig {
  static const String apiKey = 'AIzaSyC2O92uV1T65Q8Vm1Ps9FlfqGyMVTK9zYA';
  static const String appId = '1:873591143565:android:1cd6286f9a75364c7bf6c4';
  static const String messagingSenderId = '873591143565';
  static const String projectId = 'client-rhm';

  static bool get ready => apiKey.isNotEmpty && appId.isNotEmpty && messagingSenderId.isNotEmpty && projectId.isNotEmpty;
}
