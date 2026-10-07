import 'dart:async';
import 'dart:convert';
import 'dart:math';
import 'dart:ui';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'model.dart';
import 'net.dart';

/// Etat de l'application : ecoute UDP, table de presence, position lissee, mesure GATT.
class Controller extends ChangeNotifier {
  final Net net = Net();
  final RingTable table = RingTable();
  final Map<String, GwCfg> cfg = {};
  final Gatt gatt = Gatt();

  String site = 'EIS RHM Demo';
  bool editMode = false;
  String? selectedRing;
  String? stickyGw; // gateway courante (avec hysteresis)
  String? chosenGw; // gateway choisie a la main pour la mesure (null = automatique)
  Offset? pos; // position lissee (0..100)
  Offset? lastStablePos;
  double radius = 18;
  bool localized = false;
  DateTime? lastRx;
  String? lastZone; // derniere zone ou la bague a ete detectee
  DateTime? lastSeenAt;
  DateTime? otherBusyAt; // une mesure lancee par quelqu'un d'autre est en cours
  String? otherBusyGw;
  String? toast;

  Timer? _tick;
  StreamSubscription<Map<String, dynamic>>? _sub;

  static const _slots = [
    Offset(22, 35), Offset(78, 65), Offset(22, 72), Offset(78, 28), Offset(50, 50),
  ];

  Future<void> start() async {
    await _load();
    await net.start();
    _sub = net.messages.listen(_onMessage);
    _tick = Timer.periodic(const Duration(milliseconds: 500), (_) => _onTick());
    notifyListeners();
  }

  @override
  void dispose() {
    _tick?.cancel();
    _sub?.cancel();
    net.stop();
    super.dispose();
  }

  // ------------------------------------------------------------------ reception

  void _onMessage(Map<String, dynamic> m) {
    final type = m['type'];
    if (type == 'OBS') {
      final gw = table.update(m);
      if (gw == null) return;
      lastRx = DateTime.now();
      _ensureGateway(gw, m['zone']?.toString());
      selectedRing ??= (m['ring'] ?? '').toString().toUpperCase().trim();
    } else if (type == 'GATT_STATUS' || type == 'GATT_RESULT') {
      _onGatt(m, type == 'GATT_RESULT');
    }
  }

  void _ensureGateway(String gw, String? zone) {
    final existing = cfg[gw];
    if (existing != null) {
      if ((existing.zone.isEmpty) && zone != null && zone.isNotEmpty) existing.zone = zone;
      return;
    }
    final slot = _slots[cfg.length % _slots.length];
    cfg[gw] = GwCfg(gw, (zone != null && zone.isNotEmpty) ? zone : gw, slot.dx, slot.dy);
    _save();
  }

  void _onGatt(Map<String, dynamic> m, bool isResult) {
    final req = m['req']?.toString();
    if (req == null) return;
    if (req == gatt.req) {
      gatt.status = (m['status'] ?? gatt.status).toString();
      gatt.gateway = (m['gateway'] ?? gatt.gateway)?.toString();
      if (m['value'] is num) gatt.value = (m['value'] as num).toInt();
      if (m['battery'] is num) gatt.battery = (m['battery'] as num).toInt();
      if (m['charging'] is bool) gatt.charging = m['charging'] as bool;
      gatt.at = DateTime.now();
      if (isResult) {
        gatt.done = true;
        gatt.functional = m['functional_state']?.toString();
        gatt.reason = m['reason']?.toString();
      } else if (gatt.status == 'BUSY') {
        gatt.done = true;
        gatt.functional = 'BUSY';
      }
      notifyListeners();
    } else if (!isResult) {
      // Mesure lancee par un autre client : on bloque notre bouton
      otherBusyAt = DateTime.now();
      otherBusyGw = m['gateway']?.toString();
      notifyListeners();
    } else {
      otherBusyAt = null;
      notifyListeners();
    }
  }

  // ------------------------------------------------------------------ calcul periodique

  void _onTick() {
    table.purge();
    final ring = selectedRing;
    if (ring != null && !table.data.containsKey(ring) && table.rings.isNotEmpty) {
      selectedRing = table.rings.first;
    }
    final r = selectedRing;
    final cands = r == null ? <Obs>[] : table.candidates(r);

    // Gateway courante avec hysteresis de 3 dB (anti-clignotement)
    if (cands.isEmpty) {
      localized = false;
    } else {
      localized = true;
      final best = cands.first;
      final cur = cands.where((o) => o.gw == stickyGw).toList();
      if (cur.isEmpty || best.rssi! >= cur.first.rssi! + 3) stickyGw = best.gw;
      lastZone = currentZone;
      lastSeenAt = DateTime.now();
    }

    // Position lissee (EMA)
    final target = estimatePosition(cands, cfg);
    if (target != null) {
      pos = pos == null ? target : Offset(pos!.dx + (target.dx - pos!.dx) * 0.25, pos!.dy + (target.dy - pos!.dy) * 0.25);
      lastStablePos = pos;
      final wanted = uncertainty(cands);
      radius += (wanted - radius) * 0.25;
    }

    if (otherBusyAt != null && DateTime.now().difference(otherBusyAt!).inSeconds > 90) otherBusyAt = null;
    if (!gatt.done && gatt.at != null && DateTime.now().difference(gatt.at!).inSeconds > 120) {
      gatt.done = true;
      gatt.status = 'TIMEOUT';
      gatt.functional = 'ERROR';
      gatt.reason = 'NO_ANSWER';
    }
    notifyListeners();
  }

  // ------------------------------------------------------------------ actions

  bool get measuring => !gatt.done;
  bool get busyElsewhere => otherBusyAt != null;

  String? get currentZone {
    final g = stickyGw;
    if (g == null) return null;
    final z = cfg[g]?.zone;
    return (z == null || z.isEmpty) ? g : z;
  }

  /// Lance une mesure HR. [gateway] : gateway choisie ; sinon celle choisie dans la liste,
  /// sinon automatiquement la gateway au meilleur signal.
  void measure({String? gateway}) {
    final ring = selectedRing;
    if (ring == null) { toast = 'Aucune bague detectee.'; notifyListeners(); return; }
    if (measuring || busyElsewhere) { toast = 'Mesure en cours... Patienter.'; notifyListeners(); return; }
    final cands = table.candidates(ring);
    final wanted = gateway ?? chosenGw;
    String? target;
    if (wanted != null) {
      if (!cands.any((o) => o.gw == wanted)) {
        toast = '$wanted ne voit pas la bague actuellement.';
        notifyListeners();
        return;
      }
      target = wanted;
    } else {
      target = cands.any((o) => o.gw == stickyGw) ? stickyGw : (cands.isEmpty ? null : cands.first.gw);
    }
    if (target == null) { toast = 'Bague non detectee : mesure impossible.'; notifyListeners(); return; }
    final req = 'hr-${_hex(10)}';
    gatt
      ..req = req
      ..ring = ring
      ..gateway = target
      ..status = 'REQUESTED'
      ..done = false
      ..value = null
      ..functional = null
      ..reason = null
      ..at = DateTime.now();
    net.sendCommand({
      'type': 'GATT_CMD',
      'version': 5,
      'req': req,
      'target': target,
      'ring': ring,
      'cmd': 'hr',
      'ts': DateTime.now().toIso8601String(),
    });
    notifyListeners();
  }

  String _hex(int n) {
    final r = Random.secure();
    return List.generate(n, (_) => r.nextInt(16).toRadixString(16)).join();
  }

  void setChosenGw(String? gw) {
    chosenGw = gw;
    notifyListeners();
  }

  void selectRing(String r) {
    selectedRing = r;
    pos = null;
    stickyGw = null;
    notifyListeners();
  }

  void moveGateway(String gw, double x, double y) {
    final c = cfg[gw];
    if (c == null) return;
    c.x = x.clamp(4.0, 96.0);
    c.y = y.clamp(6.0, 94.0);
    notifyListeners();
  }

  void renameZone(String gw, String zone) {
    cfg[gw]?.zone = zone;
    _save();
    notifyListeners();
  }

  void setSite(String s) {
    site = s;
    _save();
    notifyListeners();
  }

  void setEditMode(bool v) {
    editMode = v;
    if (!v) _save();
    notifyListeners();
  }

  void clearToast() => toast = null;

  // ------------------------------------------------------------------ sauvegarde locale

  Future<void> _load() async {
    try {
      final sp = await SharedPreferences.getInstance();
      site = sp.getString('site') ?? site;
      final raw = sp.getString('cfg');
      if (raw != null) {
        final list = jsonDecode(raw) as List;
        for (final e in list) {
          final c = GwCfg.fromJson(e as Map<String, dynamic>);
          cfg[c.name] = c;
        }
      }
    } catch (_) {}
  }

  Future<void> _save() async {
    try {
      final sp = await SharedPreferences.getInstance();
      await sp.setString('site', site);
      await sp.setString('cfg', jsonEncode(cfg.values.map((c) => c.toJson()).toList()));
    } catch (_) {}
  }
}
