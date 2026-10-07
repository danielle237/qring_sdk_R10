// État de l'app : compte, bagues en temps réel (flux SSE du serveur, venu de Mosquitto),
// alertes, vérification « Actualiser l'état » (même règle que la TV : 15 s sans problème = portée).
import 'dart:async';

import 'package:flutter/widgets.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api.dart';
import 'i18n.dart';
import 'push.dart';

int nowSec() => DateTime.now().millisecondsSinceEpoch ~/ 1000;

class RingItem {
  final String mac;
  final String key;
  String label;
  String name;
  String model;
  Map<String, dynamic> rights;
  bool notify;
  Map<String, dynamic> live;

  RingItem.fromJson(Map<String, dynamic> j)
      : mac = j['mac'] as String,
        key = j['key'] as String,
        label = (j['label'] ?? j['mac']) as String,
        name = (j['name'] ?? '') as String,
        model = (j['model'] ?? '') as String,
        rights = Map<String, dynamic>.from(j['rights'] as Map),
        notify = j['notify'] == true,
        live = Map<String, dynamic>.from((j['live'] ?? {}) as Map);

  /// Vrai nom Bluetooth de la bague (ex. « R10_6401 ») envoyé par la GATEWAY RHM, sinon le nom en base.
  String get realName {
    final b = (live['bleName'] as String?) ?? '';
    return b.isNotEmpty ? b : name;
  }

  /// Titre affiché partout : le nom Bluetooth de la bague (« R10_6401 »), sinon le nom donné par l'admin.
  String get title {
    final b = (live['bleName'] as String?) ?? '';
    if (b.isNotEmpty) return b;
    return label.isNotEmpty ? label : (name.isNotEmpty ? name : mac);
  }

  /// Nom donné dans l'admin (base de données, ex. « Mme Martin »), affiché entre parenthèses
  /// sous le nom Bluetooth. Il reste après un redémarrage ; un nouveau nom de l'admin le remplace.
  String? get subName {
    for (final n in [label, name]) {
      if (n.isNotEmpty && n != title && n != mac && n != realName) return n;
    }
    return null;
  }

  /// Nom du résident (« Mme Martin ») : nom affiché de l'admin, sinon le nom de la bague.
  String get resident {
    for (final n in [label, name]) {
      if (n.isNotEmpty && n != mac) return n;
    }
    return realName.isNotEmpty ? realName : mac;
  }

  /// Identifiant de la bague sous le nom du résident (« R10_6401 »).
  String get ringId => realName.isNotEmpty && realName != resident ? realName : mac;

  /// Pièce où la bague est entendue (« Chambre 12 »), dernière pièce, zone principale.
  String? get zone => live['zone'] as String?;
  String? get lastZone => live['lastZone'] as String?;
  String? get mainZone => live['mainZone'] as String?;
  Map<String, dynamic>? get location => live['location'] == null ? null : Map<String, dynamic>.from(live['location'] as Map);

  bool get online => live['online'] == true;
  String get ringState => (live['ring'] ?? 'unknown') as String;
  /// Gateway RHM Linux : pas de surveillance Bluetooth permanente, « hors portée » = dernier échec.
  bool get isLinux => live['gatewayType'] == 'linux';
  /// Bague sur TV Android : boutons masquables depuis l'admin (global ou par bague)
  bool get showAllBtn => isLinux || live['tvShowAll'] != false;
  bool get showOtherBtn => isLinux || live['tvShowOther'] != false;
  /// Réglage global de l'admin : afficher le type de Gateway (Linux / Android) sur la pastille.
  bool get showGatewayType => live['showGatewayType'] == true;
  /// Mesure / Actualiser possibles : bague connectée, ou Gateway Linux (la mesure revérifie la bague).
  bool get canTry =>
      ringState == 'connected' || (isLinux && (ringState == 'disconnected' || ringState == 'connecting'));
  bool? get worn => live['worn'] as bool?;
  int? get battery => (live['battery'] as num?)?.toInt();
  /// Heure de la dernière valeur de batterie (0 si inconnue).
  int get batteryTs {
    final a = (live['batteryTs'] as num?)?.toInt() ?? 0;
    final b = ((values['battery'] as Map?)?['ts'] as num?)?.toInt() ?? 0;
    return a > b ? a : b;
  }
  bool get charging => live['charging'] == true;
  Map<String, dynamic> get values => Map<String, dynamic>.from((live['values'] ?? {}) as Map);
  Map<String, dynamic> get pending => Map<String, dynamic>.from((live['pending'] ?? {}) as Map);
  Map<String, dynamic> get errors => Map<String, dynamic>.from((live['errors'] ?? {}) as Map);
  List<String> get measures => List<String>.from((rights['measures'] ?? []) as List);
  List<String> get visible => List<String>.from((rights['visible'] ?? []) as List);
  bool get canHistory => rights['history'] == true;
  bool get canAlerts => rights['alerts'] == true;

  /// Mesure « live » en cours (hr, spo2…), s'il y en a une.
  String? get runningMeasure {
    // « all » d'abord (ALL = HR → SpO₂ → T° → HRV), puis toute autre mesure en cours (fatigue, health, pas…)
    if (pending.containsKey('all')) return 'all';
    const m = ['hr', 'spo2', 'temp', 'bp', 'hrv', 'stress', 'fatigue', 'health', 'steps'];
    for (final k in pending.keys) {
      if (m.contains(k)) return k;
    }
    return null;
  }
}

/// Vérification « Actualiser l'état » d'une bague.
enum CheckPhase { requested, checking, wornMeasuring, worn, reachable, removed, out, gwOff, waiting, unconfirmed, failed }

class CheckState {
  CheckPhase phase;
  int started;          // heure serveur (s)
  int? measureStart;
  int? wornAt;
  String? value;
  String? message;
  String? busyCmd;
  /// Commande de vérification : « hr » (TV Android) ou « reach » (Gateway Linux : test de portée)
  String cmd = 'hr';
  bool popupShown = false;
  /// Heure (téléphone) où le résultat est devenu définitif : le bandeau disparaît après 60 s.
  int? doneAt;
  CheckState(this.phase, this.started);
  bool get running =>
      phase == CheckPhase.requested || phase == CheckPhase.checking || phase == CheckPhase.wornMeasuring ||
      phase == CheckPhase.waiting;
}

class AppModel extends ChangeNotifier with WidgetsBindingObserver {
  final Api api = Api.instance;
  SharedPreferences? _prefs;

  bool ready = false;
  Map<String, dynamic>? user;
  List<RingItem> rings = [];
  List<Map<String, dynamic>> alerts = [];
  bool streaming = false;
  /// Alertes déjà vues (pastille rouge de l'onglet Alertes)
  int alertsSeenTs = 0;
  int get unreadAlerts => alerts.where((a) => ((a['ts'] as num?) ?? 0) > alertsSeenTs).length;
  int wearCheck = 15;
  int _skew = 0; // heure serveur - heure du téléphone

  final Map<String, CheckState> checks = {};
  final StreamController<Map<String, dynamic>> uiEvents = StreamController.broadcast();

  StreamSubscription? _sub;
  Timer? _reconnect;
  Timer? _ticker;
  bool _foreground = true;

  bool get loggedIn => user != null && api.token != null;
  int serverNow() => nowSec() + _skew;

  // ------------------------------------------------------------------ démarrage / connexion
  Future<void> init() async {
    WidgetsBinding.instance.addObserver(this);
    _prefs = await SharedPreferences.getInstance();
    api.server = _prefs!.getString('server') ?? kDefaultServer;
    appLang = _prefs!.getString('lang') ?? 'fr';
    alertsSeenTs = _prefs!.getInt('alertsSeenTs') ?? 0;
    final token = _prefs!.getString('token');
    try {
    if (token != null) {
      api.token = token;
      try {
        final r = await api.me();
        _setUser(r['user']);
        await _afterLogin();
      } on ApiException catch (e) {
        if (e.isAuth) {
          api.token = null;
          await _prefs!.remove('token');
        } else {
          // Hors ligne au démarrage : on garde la session, le flux se reconnectera
          user = {'name': _prefs!.getString('userName') ?? '', 'login': _prefs!.getString('login') ?? ''};
          _startStream();
          _ticker ??= Timer.periodic(const Duration(seconds: 1), (_) => _tick());
        }
      }
    }
    } catch (_) {
      // Erreur inattendue : on affiche quand même l'app
    } finally {
      ready = true;
      notifyListeners();
    }
  }

  String get lastLogin => _prefs?.getString('login') ?? '';

  /// Langue choisie avant la connexion.
  void setLocalLang(String l) {
    appLang = l;
    _prefs?.setString('lang', l);
    notifyListeners();
  }

  Future<void> login(String login, String password, bool keep, String server) async {
    api.server = server.trim().isEmpty ? kDefaultServer : server.trim();
    await _prefs!.setString('server', api.server);
    final chosenLang = appLang;
    final r = await api.login(login.trim(), password);
    api.token = r['token'] as String;
    _setUser(r['user']);
    // Langue choisie sur l'écran de connexion : gardée et enregistrée sur le serveur
    if (user!['lang'] != chosenLang) {
      try {
        _setUser((await api.prefs({'lang': chosenLang}))['user']);
      } catch (_) {
        appLang = chosenLang;
      }
    }
    await _prefs!.setString('login', login.trim());
    if (keep) {
      await _prefs!.setString('token', api.token!);
    } else {
      await _prefs!.remove('token');
    }
    await _afterLogin();
    notifyListeners();
  }

  void _setUser(dynamic u) {
    user = Map<String, dynamic>.from(u as Map);
    final lang = user!['lang'] as String?;
    if (lang != null && lang.isNotEmpty) {
      appLang = lang;
      _prefs?.setString('lang', lang);
    }
    _prefs?.setString('userName', '${user!['name'] ?? ''}');
  }

  Future<void> _afterLogin() async {
    await refreshRings();
    unawaited(loadAlerts());
    _startStream();
    _ticker ??= Timer.periodic(const Duration(seconds: 1), (_) => _tick());
    // Notifications Firebase (sans effet si Firebase n'est pas configuré)
    unawaited(Push.register(api));
  }

  Future<void> logout() async {
    try {
      await api.logout(Push.token);
    } catch (_) {}
    _stopStream();
    _ticker?.cancel();
    _ticker = null;
    api.token = null;
    user = null;
    rings = [];
    alerts = [];
    checks.clear();
    await _prefs?.remove('token');
    notifyListeners();
  }

  void _authLost() {
    if (!loggedIn) return;
    logout();
  }

  // ------------------------------------------------------------------ bagues
  Future<void> refreshRings() async {
    try {
      final r = await api.rings();
      rings = (r['rings'] as List).map((j) => RingItem.fromJson(Map<String, dynamic>.from(j as Map))).toList();
      if (r['user'] != null) _setUser(r['user']);
      _updateSkew(rings.isNotEmpty ? rings.first.live : null);
      notifyListeners();
      if (_foreground) _autoCheckTv();
    } on ApiException catch (e) {
      if (e.isAuth) _authLost();
    }
  }

  /// Ouverture de l'app : bagues sur TV Android → batterie + HR (portée / retirée).
  /// Pas si l'info a moins de 5 min (ex. un autre compte vient de le faire), ni pendant une mesure.
  void _autoCheckTv() {
    final t = serverNow();
    for (final r in rings) {
      if (r.isLinux || !r.online || r.ringState != 'connected' || r.runningMeasure != null) continue;
      if (checks[r.mac]?.running == true) continue;
      final last = [
        (r.live['wornTs'] as num?)?.toInt() ?? 0,
        (r.live['removedTs'] as num?)?.toInt() ?? 0,
        (((r.values['hr'] as Map?)?['ts']) as num?)?.toInt() ?? 0,
      ].reduce((a, b) => a > b ? a : b);
      if (t - last < 300) continue;
      startCheck(r);
    }
  }

  RingItem? ringByMac(String mac) {
    for (final r in rings) {
      if (r.mac == mac) return r;
    }
    return null;
  }

  void _updateSkew(Map<String, dynamic>? live) {
    final n = (live?['now'] as num?)?.toInt();
    if (n != null) _skew = n - nowSec();
  }

  Future<void> loadAlerts() async {
    try {
      final r = await api.alerts();
      alerts = (r['alerts'] as List).map((a) => Map<String, dynamic>.from(a as Map)).toList();
      notifyListeners();
    } on ApiException catch (e) {
      if (e.isAuth) _authLost();
    }
  }

  void markAlertsSeen() {
    var maxTs = alertsSeenTs;
    for (final a in alerts) {
      final t = ((a['ts'] as num?) ?? 0).toInt();
      if (t > maxTs) maxTs = t;
    }
    if (maxTs != alertsSeenTs) {
      alertsSeenTs = maxTs;
      _prefs?.setInt('alertsSeenTs', maxTs);
      notifyListeners();
    }
  }

  Future<void> setNotifyAll(bool on) async {
    await api.notifyAll(on);
    for (final r in rings) {
      r.notify = on;
    }
    notifyListeners();
  }

  Future<void> setNotifyRing(RingItem r, bool on) async {
    await api.notifyRing(r.key, on);
    r.notify = on;
    notifyListeners();
  }

  Future<void> setPrefs(Map<String, dynamic> p) async {
    final r = await api.prefs(p);
    _setUser(r['user']);
    notifyListeners();
  }

  Future<void> changePassword(String oldP, String newP) async {
    final r = await api.password(oldP, newP);
    api.token = r['token'] as String;
    if (_prefs!.getString('token') != null) await _prefs!.setString('token', api.token!);
  }

  // ------------------------------------------------------------------ temps réel
  void _startStream() {
    if (_sub != null || !_foreground || api.token == null) return;
    _reconnect?.cancel();
    _sub = api.stream().listen(_onEvent, onError: (Object e) {
      _sub = null;
      streaming = false;
      notifyListeners();
      if (e is ApiException && e.isAuth) {
        _authLost();
        return;
      }
      _scheduleReconnect();
    }, onDone: () {
      _sub = null;
      streaming = false;
      notifyListeners();
      _scheduleReconnect();
    }, cancelOnError: true);
  }

  void _scheduleReconnect() {
    _reconnect?.cancel();
    if (!_foreground || api.token == null) return;
    _reconnect = Timer(const Duration(seconds: 3), _startStream);
  }

  void _stopStream() {
    _reconnect?.cancel();
    _sub?.cancel();
    _sub = null;
    streaming = false;
  }

  void _onEvent(Map<String, dynamic> e) {
    switch (e['type']) {
      case 'hello':
        streaming = true;
        rings = (e['rings'] as List).map((j) => RingItem.fromJson(Map<String, dynamic>.from(j as Map))).toList();
        if (rings.isNotEmpty) _updateSkew(rings.first.live);
        break;
      case 'ring':
        final r = ringByMac(e['mac'] as String);
        if (r != null) {
          final wasAway = r.ringState == 'disconnected' || r.ringState == 'connecting' || r.ringState == 'unbound';
          r.live = Map<String, dynamic>.from(e['live'] as Map);
          _updateSkew(r.live);
          _evaluate(r);
          // Retour de la bague (hors portée ou dissociée → connectée) : popup « Content de vous revoir »
          if (wasAway && r.online && r.ringState == 'connected') {
            uiEvents.add({'type': 'back', 'mac': r.mac});
          }
        }
        break;
      case 'measure_free':
        // La mesure d'un autre compte est finie : l'app propose de lancer la nôtre (Oui / Non)
        uiEvents.add({'type': 'free', 'mac': e['mac'], 'cmd': e['cmd'], 'by': e['by'], 'result': e['result']});
        break;
      case 'alert':
        final a = Map<String, dynamic>.from(e['alert'] as Map);
        alerts.insert(0, a);
        uiEvents.add({'type': 'alert', 'alert': a});
        break;
    }
    notifyListeners();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _foreground = state == AppLifecycleState.resumed;
    if (_foreground && loggedIn) {
      refreshRings();
      loadAlerts();
      _startStream();
    } else if (!_foreground) {
      // En arrière-plan : pas de flux (batterie) ; les alertes arrivent par Firebase
      _stopStream();
    }
  }

  // ------------------------------------------------------------------ mesures
  /// Lance une mesure ; réponse complète du serveur (gateway, « Patientez : … » si le Pi est occupé).
  Future<Map<String, dynamic>> measureRaw(RingItem r, String cmd) => api.cmd(r.key, cmd);

  Future<void> cancelMeasure(RingItem r) async {
    await api.cancel(r.key);
  }

  Future<String> measure(RingItem r, String cmd) async {
    final res = await api.cmd(r.key, cmd);
    return res['already'] == true ? tr('cmd.already') : tr('cmd.sent');
  }

  // ------------------------------------------------------------------ « Actualiser l'état »
  final Map<String, int> _autoChecked = {};

  /// Ouverture de la page d'une bague : vérification automatique (pas plus d'une fois par minute).
  void autoCheck(RingItem r) {
    final t = DateTime.now().millisecondsSinceEpoch ~/ 1000;
    if (t - (_autoChecked[r.mac] ?? 0) < 60) return;
    final cur = checks[r.mac];
    if (cur != null && (cur.running || (cur.doneAt != null && t - cur.doneAt! < 60))) return;
    if (!r.online || !r.canTry) return;
    _autoChecked[r.mac] = t;
    startCheck(r);
  }

  Future<void> startCheck(RingItem r) async {
    final cur = checks[r.mac];
    if (cur != null && cur.running && cur.phase != CheckPhase.waiting) return;
    try {
      final res = await api.check(r.key);
      if (res['busy'] != null) {
        final st = CheckState(CheckPhase.waiting, serverNow())..busyCmd = res['busy'] as String;
        checks[r.mac] = st;
        uiEvents.add({'type': 'busy', 'mac': r.mac, 'cmd': st.busyCmd});
      } else {
        wearCheck = (res['wearCheck'] as num?)?.toInt() ?? 15;
        checks[r.mac] = CheckState(CheckPhase.requested, (res['started'] as num?)?.toInt() ?? serverNow())
          ..cmd = (res['cmd'] as String?) ?? 'hr';
      }
    } on ApiException catch (e) {
      if (e.isAuth) {
        _authLost();
        return;
      }
      final phase = e.reason == 'ring_disconnected'
          ? CheckPhase.out
          : e.reason == 'gateway_offline'
              ? CheckPhase.gwOff
              : CheckPhase.failed;
      checks[r.mac] = CheckState(phase, serverNow())..message = e.message;
    }
    notifyListeners();
  }

  void _tick() {
    var changed = false;
    for (final r in rings) {
      final st = checks[r.mac];
      if (st == null) continue;
      if (st.running) {
        _evaluate(r);
        changed = true;
      } else {
        // Résultat affiché 60 s puis retiré : l'état en direct de la bague reprend la main
        st.doneAt ??= nowSec();
        if (nowSec() - st.doneAt! > 60) {
          checks.remove(r.mac);
          changed = true;
        }
      }
    }
    if (changed) notifyListeners();
  }

  void _evaluate(RingItem r) {
    final st = checks[r.mac];
    if (st == null || !st.running) return;
    final now = serverNow();

    // Attente de la fin d'une autre mesure, puis vérification
    if (st.phase == CheckPhase.waiting) {
      if (r.runningMeasure == null) {
        checks.remove(r.mac);
        startCheck(r);
      } else if (now - st.started > 200) {
        st.phase = CheckPhase.unconfirmed;
      }
      return;
    }
    if (!r.online) {
      st.phase = CheckPhase.gwOff;
      return;
    }
    if (st.cmd == 'reach') {
      // Gateway Linux : test de portée (écoute seule) → « à portée » (avec le signal) ou « hors portée »
      final re = r.errors['reach'] as Map?;
      if (re != null && ((re['ts'] as num?) ?? 0) >= st.started - 5) {
        st.phase = re['code'] == 'ring_disconnected' ? CheckPhase.out : CheckPhase.unconfirmed;
        if (st.phase == CheckPhase.unconfirmed) st.message = tr('err.${re['code']}');
        return;
      }
      final rv = r.values['reach'] as Map?;
      if (rv != null && ((rv['ts'] as num?) ?? 0) >= st.started - 5) {
        st.phase = CheckPhase.reachable;
        st.wornAt ??= now;
        final d = (rv['data'] as Map?) ?? const {};
        final rssi = d['rssi'];
        final gw = d['gateway'];
        st.value = [if (rssi != null) '📶 $rssi dBm', if (gw != null) '$gw'].join(' · ');
        if (st.value!.isEmpty) st.value = null;
        return;
      }
      if (now - st.started > 40) st.phase = CheckPhase.unconfirmed;
      return;
    }
    final err = r.errors['hr'] as Map?;
    if (err != null && ((err['ts'] as num?) ?? 0) >= st.started - 5) {
      final code = err['code'] as String?;
      if (code == 'ring_removed') {
        st.phase = CheckPhase.removed;
      } else if (code == 'ring_disconnected') {
        st.phase = CheckPhase.out;
      } else if (st.wornAt != null) {
        st.phase = CheckPhase.worn;
      } else {
        st.phase = CheckPhase.unconfirmed;
        st.message = tr('err.$code');
      }
      return;
    }
    final val = r.values['hr'] as Map?;
    if (val != null && ((val['ts'] as num?) ?? 0) >= st.started - 5) {
      st.phase = CheckPhase.worn;
      st.wornAt ??= now;
      final v = (val['data'] as Map?)?['value'];
      st.value = v == null ? null : '❤️ ${tr('btn.hr')} $v bpm';
      return;
    }
    if (!r.canTry) {
      st.phase = CheckPhase.out;
      return;
    }
    final p = r.pending['hr'] as Map?;
    if (p != null && p['confirmed'] == true) {
      final since = (p['since'] as num?)?.toInt() ?? now;
      st.measureStart = since;
      if (st.wornAt == null && now - since >= wearCheck) st.wornAt = now;
      st.phase = st.wornAt != null ? CheckPhase.wornMeasuring : CheckPhase.checking;
    }
    if (now - st.started > 60 + 60) {
      st.phase = st.wornAt != null ? CheckPhase.worn : CheckPhase.unconfirmed;
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _stopStream();
    _ticker?.cancel();
    uiEvents.close();
    super.dispose();
  }
}
