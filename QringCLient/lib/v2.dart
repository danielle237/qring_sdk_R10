// Client RHM V2 — éléments communs : état de détection (vert / orange / rouge), avatar du résident,
// dessin de la bague, petite courbe, tranche « il y a … ».
import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'api.dart';
import 'i18n.dart';
import 'model.dart';
import 'widgets.dart';

/// Couleurs de la maquette V2 (sombre, accent turquoise)
class V2 {
  static const teal = Color(0xFF35E0C2);
  static const tealDark = Color(0xFF0E3B3A);
  static const green = Color(0xFF3ECF8E);
  static const orange = Color(0xFFFFA43A);
  static const red = Color(0xFFFF5A5F);
  static const grey = Color(0xFF7D869F);
  static const blue = Color(0xFF4C8DFF);
  static const card = Color(0xFF171D2E);
  static const card2 = Color(0xFF1C2338);
}

/// Seuils de la maquette : détectée ≤ 15 s · information ancienne ≤ 2 min · non détectée au-delà
const kDetectedSec = 15;
const kOldSec = 120;
const kBatteryLow = 20;

enum Det { detected, old, notDetected, gwOff, unbound }

class Detection {
  final Det det;
  final int? ageSec;      // depuis la dernière détection
  final String? zone;     // pièce actuelle (ou dernière pièce si non détectée)
  const Detection(this.det, this.ageSec, this.zone);

  bool get isDetected => det == Det.detected || det == Det.old;

  Color get color => switch (det) {
        Det.detected => V2.green,
        Det.old => V2.orange,
        Det.notDetected => V2.red,
        Det.gwOff => V2.grey,
        Det.unbound => V2.grey,
      };
}

/// « 2 s », « 4 min », « 1 h »
String shortAge(int s) {
  if (s < 0) s = 0;
  if (s < 60) return tr('v2.s', [s]);
  if (s < 3600) return tr('v2.min', [s ~/ 60]);
  if (s < 86400) return tr('v2.h', [s ~/ 3600]);
  return ago(nowSec() - s);
}

/// « il y a 2 s », « il y a 4 min »
String agoV2(int s) {
  if (s < 0) s = 0;
  if (s < 60) return tr('v2.ago_s', [s]);
  if (s < 3600) return tr('v2.ago_min', [s ~/ 60]);
  if (s < 86400) return tr('v2.ago_h', [s ~/ 3600]);
  return ago(nowSec() - s);
}

/// État de détection d'une bague :
///  * Gateway Linux (écoute passive) : âge de la dernière écoute qui a entendu la bague ;
///  * Gateway Android (TV) : bague connectée en permanence → « détectée » tant qu'elle est connectée.
Detection detectionOf(RingItem r, int now) {
  if (r.ringState == 'unbound') return Detection(Det.unbound, null, r.lastZone);
  final loc = r.location;
  final busy = r.runningMeasure != null && r.pending[r.runningMeasure] is Map &&
      (r.pending[r.runningMeasure] as Map)['confirmed'] == true;
  if (r.isLinux && loc != null && loc['mode'] != 'scan') {
    // Tour test_reachable : l'état vient du dernier test (pas de l'âge) ; « vue à 14:32 » = dernière fois entendue
    if (!r.online) return Detection(Det.gwOff, null, r.lastZone);
    final seen = (loc['seenTs'] as num?)?.toInt();
    final age = seen == null ? null : now - seen;
    if (busy || loc['reachable'] == true) return Detection(Det.detected, busy ? 0 : age, r.zone ?? r.lastZone);
    return Detection(Det.notDetected, age, (r.live['lastSeenZone'] as String?) ?? r.lastZone);
  }
  if (r.isLinux && loc != null) {
    final seen = ((loc['seenTs'] ?? loc['ts']) as num?)?.toInt();
    final age = seen == null ? null : now - seen;
    if (busy) return Detection(Det.detected, 0, r.zone ?? r.lastZone);
    if (loc['reachable'] == true && age != null && age <= kDetectedSec) {
      return Detection(Det.detected, age, r.zone ?? r.lastZone);
    }
    if (age != null && age <= kOldSec) return Detection(Det.old, age, r.zone ?? r.lastZone);
    return Detection(Det.notDetected, age, r.lastZone);
  }
  final st = (r.live['statusTs'] as num?)?.toInt() ?? 0;
  if (!r.online) return Detection(Det.gwOff, st > 0 ? now - st : null, r.lastZone ?? _tvName(r));
  if (r.ringState == 'connected') return Detection(Det.detected, null, r.zone ?? _tvName(r));
  final out = (r.live['outTs'] as num?)?.toInt() ?? 0;
  return Detection(Det.notDetected, out > 0 ? now - out : null, r.lastZone ?? _tvName(r));
}

String? _tvName(RingItem r) {
  final d = (r.live['deviceName'] as String?) ?? '';
  if (d.isNotEmpty) return d;
  final g = (r.live['gateway'] as String?) ?? '';
  return g.isEmpty ? null : g;
}

bool batteryLow(RingItem r) => r.battery != null && r.battery! <= kBatteryLow && !r.charging;

/// Ligne d'état de la carte : « ● Détectée · il y a 2 s »
({Color color, String text}) cardLine(RingItem r, Detection d) {
  switch (d.det) {
    case Det.detected:
      if (batteryLow(r)) return (color: V2.orange, text: '${tr('v2.battery_low')} · ${r.battery} %');
      return (
        color: V2.green,
        // Bague sur TV Android : « Associée » (connectée à la TV) au lieu de « Détectée »
        text: d.ageSec == null
            ? tr(r.isLinux ? 'v2.detected' : 'v2.associated')
            : '${tr(r.isLinux ? 'v2.detected' : 'v2.associated')} · ${agoV2(d.ageSec!)}'
      );
    case Det.old:
      return (color: V2.orange, text: '${tr('v2.old')} · ${shortAge(d.ageSec ?? 0)}');
    case Det.notDetected:
      return (
        color: V2.red,
        text: d.ageSec == null
            ? tr('v2.not_detected')
            : '${tr('v2.not_detected')} · ${dayHm(nowSec() - d.ageSec!)} (${shortAge(d.ageSec!)})'
      );
    case Det.gwOff:
      return (color: V2.grey, text: tr('v2.gw_off'));
    case Det.unbound:
      return (color: V2.grey, text: tr('v2.unbound'));
  }
}

/// Ligne de pièce : « Chambre 12 » ou « Dernière zone : Salon »
String? zoneLine(Detection d) {
  if (d.zone == null || d.zone!.isEmpty) return null;
  return d.isDetected ? d.zone : tr('v2.last_zone', [d.zone]);
}

const _avatarColors = [
  Color(0xFFF48FB1), Color(0xFF64B5F6), Color(0xFFB39DDB), Color(0xFF81C784),
  Color(0xFFFFB74D), Color(0xFF4DD0E1), Color(0xFFE57373), Color(0xFFAED581),
];

/// Avatar rond du résident : sa photo (envoyée depuis l'admin, rechargée dès qu'elle change),
/// sinon une silhouette de couleur stable par bague
class ResidentAvatar extends StatelessWidget {
  final RingItem r;
  final double size;
  final bool dim;
  const ResidentAvatar(this.r, {super.key, this.size = 46, this.dim = false});
  @override
  Widget build(BuildContext context) {
    final v = (r.live['photoV'] as num?)?.toInt();
    final api = Api.instance;
    if (v != null && api.token != null) {
      final base = api.server.endsWith('/') ? api.server.substring(0, api.server.length - 1) : api.server;
      final img = ClipOval(
        child: Image.network(
          '$base/api/client/ring/${r.key}/photo?v=$v',     // nouvelle version → nouvelle adresse → rechargée
          key: ValueKey('${r.mac}-$v'),
          headers: {'Authorization': 'Bearer ${api.token}'},
          width: size,
          height: size,
          fit: BoxFit.cover,
          gaplessPlayback: true,
          errorBuilder: (_, __, ___) => _silhouette(),
        ),
      );
      return dim ? Opacity(opacity: .55, child: img) : img;
    }
    return _silhouette();
  }

  Widget _silhouette() {
    final c = dim ? V2.grey : _avatarColors[r.mac.codeUnits.fold<int>(0, (a, b) => a + b) % _avatarColors.length];
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        gradient: LinearGradient(
            colors: [c.withOpacity(.95), c.withOpacity(.6)], begin: Alignment.topLeft, end: Alignment.bottomRight),
      ),
      child: Icon(Icons.person, color: Colors.white.withOpacity(.92), size: size * .62),
    );
  }
}

/// Petite batterie + pourcentage (en haut à droite des cartes)
class BatteryChip extends StatelessWidget {
  final int? value;
  final bool charging;
  const BatteryChip(this.value, {super.key, this.charging = false});
  @override
  Widget build(BuildContext context) {
    final v = value;
    final low = v != null && v <= kBatteryLow && !charging;
    final c = v == null ? V2.grey : low ? V2.red : V2.green;
    return Row(mainAxisSize: MainAxisSize.min, children: [
      Container(
        width: 22,
        height: 13,
        padding: const EdgeInsets.all(1.5),
        decoration: BoxDecoration(border: Border.all(color: c, width: 1.6), borderRadius: BorderRadius.circular(3)),
        child: Align(
          alignment: Alignment.centerLeft,
          child: FractionallySizedBox(
            widthFactor: ((v ?? 0) / 100).clamp(0.05, 1.0),
            child: Container(decoration: BoxDecoration(color: c, borderRadius: BorderRadius.circular(1.5))),
          ),
        ),
      ),
      Container(width: 2, height: 6, color: c),
      const SizedBox(width: 5),
      Text(v == null ? '--' : '$v%', style: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600)),
      if (charging) const Icon(Icons.bolt, size: 14, color: V2.orange),
    ]);
  }
}

/// Batterie en cercle (fiche du résident) : le cercle se remplit selon le niveau (vert, rouge si ≤ 20 %),
/// symbole batterie au centre, pourcentage et « il y a … » en dessous
class BatteryGauge extends StatelessWidget {
  final RingItem r;
  final double size;
  const BatteryGauge(this.r, {super.key, this.size = 96});
  @override
  Widget build(BuildContext context) {
    final v = r.battery;
    final low = v != null && v <= kBatteryLow && !r.charging;
    // Batterie lue il y a plus de 6 h (lecture à la demande) : affichée en gris, valeur ancienne
    final old = r.batteryTs > 0 && DateTime.now().millisecondsSinceEpoch ~/ 1000 - r.batteryTs > 6 * 3600;
    final c = v == null || old ? V2.grey : low ? V2.red : V2.green;
    final icon = r.charging
        ? Icons.battery_charging_full
        : v == null
            ? Icons.battery_unknown
            : v >= 90
                ? Icons.battery_full
                : v >= 60
                    ? Icons.battery_5_bar
                    : v >= 30
                        ? Icons.battery_3_bar
                        : Icons.battery_1_bar;
    return SizedBox(
      width: size,
      height: size,
      child: Stack(alignment: Alignment.center, children: [
        SizedBox(
          width: size,
          height: size,
          child: CircularProgressIndicator(
            value: (v ?? 0) / 100,
            strokeWidth: size * .085,
            strokeCap: StrokeCap.round,
            backgroundColor: C.line,
            color: c,
          ),
        ),
        Column(mainAxisSize: MainAxisSize.min, children: [
          Icon(icon, color: c, size: size * .3),
          Text(v == null ? '--' : '$v %',
              style: TextStyle(fontWeight: FontWeight.w800, fontSize: size * .17, height: 1.1)),
          if (r.batteryTs > 0)
            Text(ago(r.batteryTs), style: TextStyle(color: C.muted, fontSize: size * .1)),
        ]),
      ]),
    );
  }
}

/// Dessin de la bague (anneau métallique + pierre turquoise), avec ondes Bluetooth animées si [waves]
class RingArt extends StatefulWidget {
  final double size;
  final bool waves;
  const RingArt({super.key, this.size = 90, this.waves = false});
  @override
  State<RingArt> createState() => _RingArtState();
}

class _RingArtState extends State<RingArt> with SingleTickerProviderStateMixin {
  late final AnimationController _c =
      AnimationController(vsync: this, duration: const Duration(milliseconds: 1600));

  @override
  void initState() {
    super.initState();
    if (widget.waves) _c.repeat();
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: widget.size * (widget.waves ? 1.9 : 1),
      height: widget.size,
      child: AnimatedBuilder(
        animation: _c,
        builder: (_, __) => CustomPaint(painter: _RingPainter(widget.waves ? _c.value : null)),
      ),
    );
  }
}

class _RingPainter extends CustomPainter {
  final double? wave;
  _RingPainter(this.wave);

  @override
  void paint(Canvas canvas, Size size) {
    final h = size.height;
    final c = Offset(size.width / 2, h * .58);
    final rx = h * .36, ry = h * .30;
    // Ondes Bluetooth de chaque côté
    if (wave != null) {
      for (var i = 0; i < 3; i++) {
        final t = (wave! + i / 3) % 1.0;
        final p = Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = 3
          ..strokeCap = StrokeCap.round
          ..color = V2.blue.withOpacity((1 - t) * .9);
        final rr = rx * (1.25 + t * .9);
        final rect = Rect.fromCenter(center: c, width: rr * 2, height: rr * 1.7);
        canvas.drawArc(rect, math.pi * .8, math.pi * .4, false, p);
        canvas.drawArc(rect, -math.pi * .2, math.pi * .4, false, p);
      }
    }
    // Anneau (ellipse épaisse dégradée)
    final outer = Rect.fromCenter(center: c, width: rx * 2, height: ry * 2);
    final band = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = h * .11
      ..shader = const LinearGradient(
        colors: [Color(0xFFE9EDF5), Color(0xFF8A93A8), Color(0xFFF7F9FC), Color(0xFF5F687D)],
        stops: [0, .35, .6, 1],
      ).createShader(outer);
    canvas.drawOval(outer, band);
    final inner = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.2
      ..color = Colors.black.withOpacity(.35);
    canvas.drawOval(Rect.fromCenter(center: c, width: rx * 2 - h * .11, height: ry * 2 - h * .11), inner);
    // Pierre (capteur) turquoise en haut
    final top = Offset(c.dx, c.dy - ry - h * .02);
    final gem = Path()
      ..moveTo(top.dx - h * .1, top.dy)
      ..lineTo(top.dx - h * .06, top.dy - h * .08)
      ..lineTo(top.dx + h * .06, top.dy - h * .08)
      ..lineTo(top.dx + h * .1, top.dy)
      ..lineTo(top.dx, top.dy + h * .07)
      ..close();
    canvas.drawPath(gem, Paint()..color = const Color(0xFF7FE9FF));
    canvas.drawPath(
        gem,
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = 1.2
          ..color = Colors.white.withOpacity(.8));
    canvas.drawCircle(top.translate(0, -h * .02), h * .02, Paint()..color = Colors.white);
  }

  @override
  bool shouldRepaint(covariant _RingPainter old) => old.wave != wave;
}

/// Petite courbe (tendance des dernières valeurs)
class Sparkline extends StatelessWidget {
  final List<double> values;
  final Color color;
  final double width;
  final double height;
  const Sparkline(this.values, {super.key, this.color = V2.blue, this.width = 64, this.height = 22});
  @override
  Widget build(BuildContext context) =>
      SizedBox(width: width, height: height, child: CustomPaint(painter: _SparkPainter(values, color)));
}

class _SparkPainter extends CustomPainter {
  final List<double> v;
  final Color color;
  _SparkPainter(this.v, this.color);
  @override
  void paint(Canvas canvas, Size size) {
    if (v.length < 2) return;
    final mn = v.reduce(math.min), mx = v.reduce(math.max);
    final span = (mx - mn).abs() < 1e-6 ? 1.0 : mx - mn;
    final path = Path();
    for (var i = 0; i < v.length; i++) {
      final x = size.width * i / (v.length - 1);
      final y = size.height - 2 - (size.height - 4) * (v[i] - mn) / span;
      if (i == 0) {
        path.moveTo(x, y);
      } else {
        path.lineTo(x, y);
      }
    }
    canvas.drawPath(
        path,
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = 2
          ..strokeJoin = StrokeJoin.round
          ..color = color);
    final last = Offset(size.width, size.height - 2 - (size.height - 4) * (v.last - mn) / span);
    canvas.drawCircle(last, 2.6, Paint()..color = color);
  }

  @override
  bool shouldRepaint(covariant _SparkPainter old) => old.v != v || old.color != color;
}

/// Valeur dans la norme ? (affichage « Normal » / « À surveiller »)
bool? isNormal(String k, num? v) {
  if (v == null) return null;
  return switch (k) {
    'hr' => v >= 50 && v <= 100,
    'spo2' => v >= 95,
    'temp' => v >= 35.5 && v <= 37.8,
    'stress' => v <= 60,
    _ => null,
  };
}

/// Reconstruit le widget chaque seconde (« il y a 3 s » qui avance)
class Every extends StatefulWidget {
  final Duration period;
  final WidgetBuilder builder;
  const Every({super.key, this.period = const Duration(seconds: 1), required this.builder});
  @override
  State<Every> createState() => _EveryState();
}

class _EveryState extends State<Every> {
  late final _t = Stream.periodic(widget.period);
  @override
  Widget build(BuildContext context) => StreamBuilder(stream: _t, builder: (ctx, _) => widget.builder(ctx));
}

/// En-tête des onglets : logo · titre · « EHPAD de la Vie » · ● En direct
class TabHeader extends StatelessWidget {
  final String title;
  final bool live;
  final bool showLive;
  const TabHeader(this.title, {super.key, this.live = true, this.showLive = true});
  @override
  Widget build(BuildContext context) {
    return Row(children: [
      ClipRRect(
          borderRadius: BorderRadius.circular(10),
          child: Image.asset('assets/logo_epat.png', width: 46, height: 46, fit: BoxFit.cover)),
      const SizedBox(width: 12),
      Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title, style: const TextStyle(fontSize: 21, fontWeight: FontWeight.w800)),
          Text(tr('app.org'), style: const TextStyle(color: C.muted, fontSize: 13)),
        ]),
      ),
      if (showLive) ...[
        Icon(Icons.circle, size: 8, color: live ? V2.green : V2.orange),
        const SizedBox(width: 5),
        Text(live ? tr('v2.live') : tr('live.off'),
            style: TextStyle(color: live ? V2.green : V2.orange, fontSize: 12, fontWeight: FontWeight.w600)),
      ],
    ]);
  }
}

/// Puce de filtre (Tous / Détectés / …)
class FilterChipV2 extends StatelessWidget {
  final String label;
  final bool selected;
  final VoidCallback onTap;
  const FilterChipV2(this.label, this.selected, this.onTap, {super.key});
  @override
  Widget build(BuildContext context) {
    return InkWell(
      borderRadius: BorderRadius.circular(20),
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 8),
        decoration: BoxDecoration(
          color: selected ? V2.blue : Colors.transparent,
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: selected ? V2.blue : C.line),
        ),
        child: Text(label,
            style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600, color: selected ? Colors.white : C.text)),
      ),
    );
  }
}
