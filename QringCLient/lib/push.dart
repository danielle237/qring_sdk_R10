// Notifications Firebase Cloud Messaging (FCM).
// Le serveur (client_api.py) envoie les alertes aux téléphones dont le compte a choisi de les recevoir.
import 'dart:async';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';

import 'api.dart';
import 'firebase_config.dart';

/// Appelé par Android quand un message arrive app fermée. La notification elle-même
/// est affichée par le système ; rien d'autre à faire ici.
@pragma('vm:entry-point')
Future<void> firebaseBackgroundHandler(RemoteMessage message) async {}

class Push {
  static bool initialized = false;
  static String? token;

  /// Bague à ouvrir quand l'utilisateur touche une notification.
  static final StreamController<String> opened = StreamController.broadcast();

  /// Notification « Bague libre » touchée : données (mac, cmd, by, result) pour la popup.
  static final StreamController<Map<String, dynamic>> freeOpened = StreamController.broadcast();

  static Future<void> init() async {
    if (!FirebaseConfig.ready) return;
    try {
      await Firebase.initializeApp(
        options: const FirebaseOptions(
          apiKey: FirebaseConfig.apiKey,
          appId: FirebaseConfig.appId,
          messagingSenderId: FirebaseConfig.messagingSenderId,
          projectId: FirebaseConfig.projectId,
        ),
      );
      FirebaseMessaging.onBackgroundMessage(firebaseBackgroundHandler);
      FirebaseMessaging.onMessageOpenedApp.listen((m) {
        if (m.data['kind'] == 'measure_free') {
          freeOpened.add(Map<String, dynamic>.from(m.data));
          return;
        }
        final mac = m.data['mac'];
        if (mac is String) opened.add(mac);
      });
      initialized = true;
    } catch (_) {
      initialized = false;
    }
  }

  /// Notification qui a ouvert l'app (app fermée) : ses données (mac, kind…), null sinon.
  static Future<Map<String, dynamic>?> initialData() async {
    if (!initialized) return null;
    final m = await FirebaseMessaging.instance.getInitialMessage();
    return m == null ? null : Map<String, dynamic>.from(m.data);
  }

  /// Autorisation + enregistrement du jeton du téléphone sur le serveur.
  static Future<void> register(Api api) async {
    if (!initialized) return;
    try {
      final fm = FirebaseMessaging.instance;
      await fm.requestPermission(alert: true, badge: true, sound: true);
      token = await fm.getToken();
      if (token != null) await api.device(token!);
      fm.onTokenRefresh.listen((t) async {
        token = t;
        try {
          await api.device(t);
        } catch (_) {}
      });
    } catch (_) {}
  }
}
