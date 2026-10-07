// Appels au service qring-client-api (client_api.py) : HTTPS + jeton de connexion.
import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import 'i18n.dart';

/// Adresse par défaut du service (modifiable sur l'écran de connexion).
const String kDefaultServer = 'https://www.itigroups.biz:5060';

class ApiException implements Exception {
  final String message;
  final int status;
  final String? reason;
  /// Réponse complète du serveur (ex. « waiting » : bague occupée, vous serez prévenu)
  final Map<String, dynamic>? body;
  ApiException(this.message, {this.status = 0, this.reason, this.body});
  bool get isAuth => status == 401 && reason == 'auth';
  @override
  String toString() => message;
}

class Api {
  Api._();
  static final Api instance = Api._();

  String server = kDefaultServer;
  String? token;
  final http.Client _client = http.Client();

  Uri _uri(String path, [Map<String, String>? query]) {
    final base = server.endsWith('/') ? server.substring(0, server.length - 1) : server;
    return Uri.parse('$base/api/client$path').replace(queryParameters: query);
  }

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        if (token != null) 'Authorization': 'Bearer $token',
      };

  Future<Map<String, dynamic>> _handle(Future<http.Response> call) async {
    http.Response r;
    try {
      r = await call.timeout(const Duration(seconds: 20));
    } on TimeoutException {
      throw ApiException(tr('err.network'));
    } catch (_) {
      throw ApiException(tr('err.network'));
    }
    Map<String, dynamic> body;
    try {
      body = jsonDecode(utf8.decode(r.bodyBytes)) as Map<String, dynamic>;
    } catch (_) {
      throw ApiException('HTTP ${r.statusCode}', status: r.statusCode);
    }
    if (body['ok'] != true) {
      throw ApiException('${body['message'] ?? body['error'] ?? 'Erreur'}',
          status: r.statusCode, reason: body['reason'] as String?, body: body);
    }
    return body;
  }

  Future<Map<String, dynamic>> get(String path, [Map<String, String>? query]) =>
      _handle(_client.get(_uri(path, query), headers: _headers));

  Future<Map<String, dynamic>> post(String path, [Map<String, dynamic>? body]) =>
      _handle(_client.post(_uri(path), headers: _headers, body: jsonEncode(body ?? {})));

  // ------------------------------------------------------------------ appels
  Future<Map<String, dynamic>> login(String login, String password) =>
      post('/login', {'login': login, 'password': password});
  Future<Map<String, dynamic>> me() => get('/me');
  Future<Map<String, dynamic>> rings() => get('/rings');
  Future<Map<String, dynamic>> ring(String key) => get('/ring/$key');
  Future<Map<String, dynamic>> cmd(String key, String cmd) => post('/ring/$key/cmd', {'cmd': cmd});
  Future<Map<String, dynamic>> check(String key) => post('/ring/$key/check');
  /// « Annuler la mesure » : la gateway arrête la mesure en cours de cette bague
  Future<Map<String, dynamic>> cancel(String key) => post('/ring/$key/cancel');
  Future<Map<String, dynamic>> history(String key, String type, int hours) =>
      get('/ring/$key/history', {'type': type, 'hours': '$hours'});
  Future<Map<String, dynamic>> sleep(String key, int days) => get('/ring/$key/sleep', {'days': '$days'});
  /// Nuits sans le détail des phases (écran « Sommeil graphique » : semaine / mois / année)
  Future<Map<String, dynamic>> sleepAll(String key, int days) =>
      get('/ring/$key/sleep', {'days': '$days', 'phases': '0'});
  /// Une nuit en détail : phases + mesures enregistrées pendant la nuit
  Future<Map<String, dynamic>> sleepNight(String key, String date) => get('/ring/$key/sleep/night', {'date': date});
  Future<Map<String, dynamic>> notifyRing(String key, bool on) => post('/ring/$key/notify', {'notify': on});
  Future<Map<String, dynamic>> notifyAll(bool on) => post('/rings/notify', {'notify': on});
  Future<Map<String, dynamic>> alerts() => get('/alerts', {'limit': '100'});
  Future<Map<String, dynamic>> prefs(Map<String, dynamic> p) => post('/prefs', p);
  Future<Map<String, dynamic>> password(String oldP, String newP) => post('/password', {'old': oldP, 'new': newP});
  Future<Map<String, dynamic>> device(String fcmToken) =>
      post('/device', {'fcmToken': fcmToken, 'platform': 'android', 'appVersion': '2.0.0'});
  Future<Map<String, dynamic>> logout(String? fcmToken) => post('/logout', {'fcmToken': fcmToken ?? ''});

  /// Flux temps réel (Server-Sent Events) : une Map par message « data: ».
  /// Se termine quand la connexion tombe (l'appelant se reconnecte).
  Stream<Map<String, dynamic>> stream() async* {
    final req = http.Request('GET', _uri('/stream'))
      ..headers.addAll({'Accept': 'text/event-stream', if (token != null) 'Authorization': 'Bearer $token'});
    final client = http.Client();
    try {
      final resp = await client.send(req).timeout(const Duration(seconds: 20));
      if (resp.statusCode == 401) throw ApiException('auth', status: 401, reason: 'auth');
      if (resp.statusCode != 200) throw ApiException('HTTP ${resp.statusCode}', status: resp.statusCode);
      final lines = resp.stream.transform(utf8.decoder).transform(const LineSplitter());
      await for (final line in lines.timeout(const Duration(seconds: 45))) {
        if (!line.startsWith('data: ')) continue;
        try {
          yield jsonDecode(line.substring(6)) as Map<String, dynamic>;
        } catch (_) {}
      }
    } finally {
      client.close();
    }
  }
}
