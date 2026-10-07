import 'dart:math';
import 'dart:ui';

/// Une observation de presence envoyee par une gateway (message OBS).
class Obs {
  final String gw;
  final String ring;
  final bool reachable;
  final double? rssi;
  final String? status;
  final String? zone;
  final int? seq;
  final String? ip;
  final DateTime recv;

  Obs({
    required this.gw,
    required this.ring,
    required this.reachable,
    required this.rssi,
    required this.status,
    required this.zone,
    required this.seq,
    required this.ip,
    required this.recv,
  });

  double get ageS => DateTime.now().difference(recv).inMilliseconds / 1000.0;
}

/// Position et zone d'une gateway sur la carte (x, y en pourcent, 0..100).
class GwCfg {
  String name;
  String zone;
  double x;
  double y;
  GwCfg(this.name, this.zone, this.x, this.y);

  Map<String, dynamic> toJson() => {'name': name, 'zone': zone, 'x': x, 'y': y};
  factory GwCfg.fromJson(Map<String, dynamic> j) => GwCfg(
        j['name'] as String,
        (j['zone'] ?? '') as String,
        (j['x'] as num).toDouble(),
        (j['y'] as num).toDouble(),
      );
}

/// Table des observations : bague -> gateway -> derniere observation.
class RingTable {
  static const ttlS = 15.0; // au-dela : observation perimee
  static const removeAfterS = 120.0;

  final Map<String, Map<String, Obs>> data = {};

  /// Renvoie le nom de la gateway si c'est un message OBS valide.
  String? update(Map<String, dynamic> m) {
    if (m['type'] != 'OBS') return null;
    final ring = (m['ring'] ?? '').toString().toUpperCase().trim();
    final gw = (m['gw'] ?? m['gateway'] ?? '').toString().trim();
    if (ring.isEmpty || gw.isEmpty) return null;
    final r = m['rssi'];
    data.putIfAbsent(ring, () => {})[gw] = Obs(
      gw: gw,
      ring: ring,
      reachable: m['reachable'] == true,
      rssi: r is num ? r.toDouble() : null,
      status: m['reach_status']?.toString(),
      zone: m['zone']?.toString(),
      seq: m['seq'] is num ? (m['seq'] as num).toInt() : null,
      ip: m['source_ip']?.toString(),
      recv: DateTime.now(),
    );
    return gw;
  }

  void purge() {
    for (final ring in data.keys.toList()) {
      final g = data[ring]!;
      g.removeWhere((_, o) => o.ageS > removeAfterS);
      if (g.isEmpty) data.remove(ring);
    }
  }

  List<String> get rings => data.keys.toList()..sort();

  List<Obs> all(String ring) =>
      (data[ring]?.values.toList() ?? [])..sort((a, b) => a.gw.compareTo(b.gw));

  /// Gateways qui voient la bague maintenant, meilleur RSSI en premier.
  List<Obs> candidates(String ring) {
    final l = all(ring)
        .where((o) => o.ageS <= ttlS && o.reachable && o.rssi != null)
        .toList();
    l.sort((a, b) => b.rssi!.compareTo(a.rssi!));
    return l;
  }
}

/// Etat d'une mesure GATT (statut puis resultat).
class Gatt {
  String? req;
  String? ring;
  String? gateway;
  String status = 'PRET';
  bool done = true;
  int? value;
  int? battery;
  bool? charging;
  String? functional; // SUCCESS, CONNECTED_NOT_WORN, OUT_OF_RANGE, ERROR
  String? reason;
  DateTime? at;
}

/// Position estimee de la bague : moyenne ponderee des gateways qui la voient.
/// Plus le RSSI est fort, plus la gateway pese (distance estimee par perte de propagation).
Offset? estimatePosition(List<Obs> candidates, Map<String, GwCfg> cfg) {
  double sw = 0, sx = 0, sy = 0;
  for (final o in candidates) {
    final c = cfg[o.gw];
    if (c == null) continue;
    final d = max(0.3, min(50.0, pow(10, (-59 - o.rssi!) / 20).toDouble()));
    final w = 1 / (d * d);
    sw += w;
    sx += w * c.x;
    sy += w * c.y;
  }
  if (sw == 0) return null;
  return Offset(sx / sw, sy / sw);
}

/// Rayon d'incertitude (en pourcent de la carte) : grand si une seule gateway voit la bague
/// ou si les deux meilleures sont proches en RSSI.
double uncertainty(List<Obs> candidates) {
  if (candidates.isEmpty) return 18;
  if (candidates.length == 1) return 14;
  final diff = max(0.0, min(20.0, candidates[0].rssi! - candidates[1].rssi!));
  return 5 + (1 - diff / 20) * 10;
}
