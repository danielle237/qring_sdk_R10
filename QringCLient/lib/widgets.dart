// Couleurs, formats et petits composants partagés (même style sombre que l'app TV Gateway RHM).
import 'package:flutter/material.dart';

import 'i18n.dart';
import 'model.dart';

class C {
  static const bg = Color(0xFF0F1320);
  static const surface = Color(0xFF151A29);
  static const card = Color(0xFF1E2438);
  static const card2 = Color(0xFF252C45);
  static const line = Color(0xFF2A3150);
  static const text = Color(0xFFEEF1FA);
  static const muted = Color(0xFF8B93B0);
  static const accent = Color(0xFF6C8CFF);
  static const ok = Color(0xFF3ECF8E);
  static const warn = Color(0xFFFFB547);
  static const err = Color(0xFFFF6B6B);
  static const off = Color(0xFF6B7390);
}

class Metric {
  final String key;
  final String icon;
  final Color color;
  final String unit;
  const Metric(this.key, this.icon, this.color, this.unit);
  String get label => tr('m.$key');
}

const metrics = <Metric>[
  Metric('hr', '❤️', Color(0xFFFF5D73), 'bpm'),
  Metric('spo2', '💧', Color(0xFF4FC3F7), '%'),
  Metric('temp', '🌡', Color(0xFFFFA04D), '°C'),
  Metric('bp', '🩸', Color(0xFFB18CFF), 'mmHg'),
  Metric('hrv', '💓', Color(0xFF3ECF8E), 'ms'),
  Metric('stress', '⚡', Color(0xFFFFD23F), '/100'),
  Metric('fatigue', '😴', Color(0xFF9FA8DA), ''),
  Metric('health', '🩺', Color(0xFF26C6DA), ''),
  Metric('steps', '🚶', Color(0xFF22C1A4), ''),
];

Metric metricOf(String key) => metrics.firstWhere((m) => m.key == key, orElse: () => Metric(key, '•', C.accent, ''));

String two(int n) => n.toString().padLeft(2, '0');

String hm(int tsSec) {
  final d = DateTime.fromMillisecondsSinceEpoch(tsSec * 1000);
  return '${two(d.hour)}:${two(d.minute)}';
}

String dayHm(int tsSec) {
  final d = DateTime.fromMillisecondsSinceEpoch(tsSec * 1000);
  final n = DateTime.now();
  if (d.year == n.year && d.month == n.month && d.day == n.day) return hm(tsSec);
  return '${two(d.day)}/${two(d.month)} ${hm(tsSec)}';
}

String ago(int tsSec) {
  final d = nowSec() - tsSec;
  if (d < 60) return tr('t.now');
  if (d < 3600) return tr('t.min', [d ~/ 60]);
  if (d < 86400) return tr('t.h', [d ~/ 3600]);
  if (d < 2 * 86400) return tr('t.yesterday');
  final t = DateTime.fromMillisecondsSinceEpoch(tsSec * 1000);
  return '${two(t.day)}/${two(t.month)}';
}

/// « 💧 SpO2 99 % » : logo du capteur, nom, valeur et unité.
String measureText(String k, Map? data) {
  final mt = metricOf(k);
  return '${mt.icon} ${tr('btn.$k')} ${formatValue(k, data)}${mt.unit.isEmpty ? '' : ' ${mt.unit}'}';
}

/// Calories en kcal : certaines bagues envoient des calories (cal) → ÷ 1000 si la valeur est aberrante.
String kcal(Map? d) {
  final c = (d?['calories'] as num?)?.toDouble() ?? 0;
  final steps = (d?['steps'] as num?)?.toDouble() ?? 0;
  final k = (c > 1000 && (steps == 0 || c > steps * 2)) ? c / 1000 : c;
  return k.toStringAsFixed(1);
}

/// Origine d'une mesure : 📱 téléphone (Client RHM) · 📺 gateway (télécommande) · 🌐 à distance · ⏱ auto
String sourceLabel(String? s, [String? by, String? via]) {
  if (s == 'phone') {
    final who = by != null && by.isNotEmpty && by != '*' ? ' ${tr('src.by', [by])}' : '';
    return '📱 ${tr(via == 'r' ? 'src.phone_r' : 'src.phone_p')}$who';
  }
  if (s == 'manual') return tr('src.manual');
  if (s == 'mqtt') return '🌐 ${tr('src.mqtt')}';
  if (s == 'auto') return '⏱ ${tr('src.auto')}';
  return '';
}

/// « 72 », « 120/80 », « 2 615 »…
String formatValue(String key, Map? data) {
  if (data == null) return '--';
  switch (key) {
    case 'temp':
      final v = (data['value'] as num?)?.toDouble();
      return v == null ? '--' : v.toStringAsFixed(1).replaceAll('.', appLang == 'en' ? '.' : ',');
    case 'bp':
      return '${data['sbp'] ?? '--'}/${data['dbp'] ?? '--'}';
    case 'steps':
      final s = (data['steps'] as num?)?.toInt() ?? (data['value'] as num?)?.toInt();
      if (s == null) return '--';
      return s.toString().replaceAllMapped(RegExp(r'(\d)(?=(\d{3})+$)'), (m) => '${m[1]} ');
    default:
      final v = data['value'] as num?;
      return v == null ? '--' : v.round().toString();
  }
}

/// État d'une bague : couleur, texte, détail.
class RingStatus {
  final Color color;
  final String text;
  final String? detail;
  final bool blink;
  const RingStatus(this.color, this.text, [this.detail, this.blink = false]);
}

/// 4 états principaux : associée · portée / retirée / hors portée, ou dissociée de la GATEWAY RHM.
RingStatus ringStatus(RingItem r) {
  final ts = (r.live['statusTs'] as num?)?.toInt() ?? 0;
  if (ts == 0) return RingStatus(C.off, tr('rs.unknown'));
  if (r.ringState == 'unbound') {
    final at = (r.live['unboundTs'] as num?)?.toInt() ?? 0;
    return RingStatus(C.err, tr('rs.unbound'), at > 0 ? tr('rs.unbound_at', [dayHm(at)]) : null);
  }
  if (r.ringState == 'no_ring') return RingStatus(C.off, tr('rs.no_ring'));
  // GATEWAY RHM hors ligne : dernier état connu de la bague, en gris (plus en direct)
  if (!r.online) {
    final last = switch (r.ringState) {
      'disconnected' || 'connecting' => 'rs.a_out',
      'bluetooth_off' => 'rs.bt_off',
      _ => r.worn == false ? 'rs.a_removed' : r.worn == true ? 'rs.a_worn' : 'rs.a_connected',
    };
    return RingStatus(C.off, tr(last), tr('rs.last_state', [dayHm(ts)]));
  }
  final running = r.runningMeasure;
  String? detail;
  if (running != null) {
    final since = ((r.pending[running] as Map?)?['since'] as num?)?.toInt() ?? nowSec();
    detail = tr('rs.measuring', [tr('btn.$running'), (nowSec() - since).clamp(0, 999)]);
  }
  switch (r.ringState) {
    case 'disconnected':
    case 'connecting':
      {
        final out = (r.live['outTs'] as num?)?.toInt() ?? 0;
        return RingStatus(C.err, tr('rs.a_out'), detail ?? (out > 0 ? tr('rs.out_since', [dayHm(out), ago(out)]) : null));
      }
    case 'bluetooth_off':
      return RingStatus(C.err, tr('rs.bt_off'), detail);
  }
  if (r.worn == false) {
    final at = (r.live['removedTs'] as num?)?.toInt() ?? 0;
    return RingStatus(C.warn, tr('rs.a_removed'),
        running != null ? detail : (at > 0 ? tr('rs.removed_at', [dayHm(at), ago(at)]) : null), true);
  }
  if (r.worn == true) {
    final w = (r.live['wornTs'] as num?)?.toInt() ?? 0;
    return RingStatus(C.ok, tr('rs.a_worn'), detail ?? (w > 0 ? tr('rs.worn_at', [dayHm(w), ago(w)]) : null));
  }
  return RingStatus(C.accent, tr('rs.a_connected'), detail);
}

class StatusPill extends StatefulWidget {
  final RingStatus s;
  final double size;
  /// true : texte toujours sur une seule ligne (réduit si la place manque)
  final bool oneLine;
  const StatusPill(this.s, {super.key, this.size = 12, this.oneLine = false});
  @override
  State<StatusPill> createState() => _StatusPillState();
}

/// Pastille d'état ; « Bague retirée » clignote doucement (warning jaune).
class _StatusPillState extends State<StatusPill> with SingleTickerProviderStateMixin {
  late final AnimationController _c =
      AnimationController(vsync: this, duration: const Duration(milliseconds: 900), lowerBound: .45);

  @override
  void initState() {
    super.initState();
    _sync();
  }

  @override
  void didUpdateWidget(StatusPill old) {
    super.didUpdateWidget(old);
    _sync();
  }

  void _sync() {
    if (widget.s.blink && !_c.isAnimating) {
      _c.repeat(reverse: true);
    } else if (!widget.s.blink && _c.isAnimating) {
      _c.stop();
      _c.value = 1;
    }
    if (!widget.s.blink) _c.value = 1;
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final s = widget.s;
    return FadeTransition(
      opacity: _c,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
        decoration: BoxDecoration(color: s.color.withOpacity(.18), borderRadius: BorderRadius.circular(20)),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          Container(width: 8, height: 8, decoration: BoxDecoration(color: s.color, shape: BoxShape.circle)),
          const SizedBox(width: 6),
          widget.oneLine
              ? Text(s.text,
                  maxLines: 1,
                  softWrap: false,
                  style: TextStyle(color: s.color, fontWeight: FontWeight.w700, fontSize: widget.size))
              : Flexible(
                  child: Text(s.text,
                      style: TextStyle(color: s.color, fontWeight: FontWeight.w700, fontSize: widget.size))),
        ]),
      ),
    );
  }
}

/// Localisation en direct (Gateway Linux) : « 📍 GW-PI3 · 📶 −62 dBm · il y a 8 s »
/// ou « 📍 Bague non entendue » — mise à jour à chaque cycle de test de portée du serveur.
class LocationLine extends StatelessWidget {
  final RingItem r;
  final double size;
  const LocationLine(this.r, {super.key, this.size = 11.5});
  @override
  Widget build(BuildContext context) {
    final loc = r.live['location'] as Map?;
    if (loc == null || loc['ts'] == null) return const SizedBox.shrink();
    final ts = (loc['ts'] as num).toInt();
    final d = nowSec() - ts;
    final when = d < 60 ? tr('loc.sec', [d < 0 ? 0 : d]) : ago(ts);
    final heard = loc['reachable'] == true;
    final text = heard
        ? '📍 ${loc['gateway'] ?? '?'}${loc['rssi'] != null ? ' · 📶 ${loc['rssi']} dBm' : ''} · $when'
        : '📍 ${tr('loc.none')} · $when';
    return Padding(
      padding: const EdgeInsets.only(top: 4),
      child: FittedBox(
        fit: BoxFit.scaleDown,
        alignment: Alignment.centerLeft,
        child: Text(text,
            maxLines: 1,
            softWrap: false,
            style: TextStyle(fontSize: size, fontWeight: FontWeight.w600, color: heard ? C.muted : C.err)),
      ),
    );
  }
}

/// Pastille « GATEWAY RHM EN LIGNE / HORS LIGNE », sous l'état de la bague.
class LinkPills extends StatelessWidget {
  final RingItem r;
  final double size;
  const LinkPills(this.r, {super.key, this.size = 10.5});
  @override
  Widget build(BuildContext context) {
    final ts = (r.live['statusTs'] as num?)?.toInt() ?? 0;
    if (ts == 0) return const SizedBox.shrink();
    // « GATEWAY RHM EN LIGNE : Linux / Android » si l'admin l'a activé (réglage global)
    final type = r.showGatewayType ? (r.isLinux ? ' : Linux' : ' : Android') : '';
    return Padding(
      padding: const EdgeInsets.only(top: 5),
      // Une seule ligne : « ● GATEWAY RHM EN LIGNE : Linux » (texte réduit si l'écran est étroit)
      child: FittedBox(
        fit: BoxFit.scaleDown,
        alignment: Alignment.centerLeft,
        child: StatusPill(
            r.online ? RingStatus(C.ok, tr('rs.gw_pill_on') + type) : RingStatus(C.err, tr('rs.gw_pill_off') + type),
            size: size,
            oneLine: true),
      ),
    );
  }
}

class BatteryRing extends StatelessWidget {
  final int? value;
  final double size;
  const BatteryRing(this.value, {super.key, this.size = 52});
  @override
  Widget build(BuildContext context) {
    final v = value;
    return SizedBox(
      width: size,
      height: size,
      child: Stack(alignment: Alignment.center, children: [
        SizedBox(
          width: size,
          height: size,
          child: CircularProgressIndicator(
            value: (v ?? 0) / 100,
            strokeWidth: 5,
            backgroundColor: C.line,
            color: (v ?? 100) < 20 ? C.err : C.ok,
          ),
        ),
        // Logo batterie + pourcentage dans le cercle
        Column(mainAxisSize: MainAxisSize.min, children: [
          Icon(
            v == null
                ? Icons.battery_unknown
                : v >= 90
                    ? Icons.battery_full
                    : v >= 60
                        ? Icons.battery_5_bar
                        : v >= 30
                            ? Icons.battery_3_bar
                            : Icons.battery_1_bar,
            size: size * 0.3,
            color: (v ?? 100) < 20 ? C.err : C.ok,
          ),
          Text(v == null ? '--' : '$v%',
              style: TextStyle(fontSize: size < 55 ? 11 : 12, fontWeight: FontWeight.w700, color: C.text, height: 1.1)),
        ]),
      ]),
    );
  }
}

class Panel extends StatelessWidget {
  final Widget child;
  final EdgeInsets padding;
  final Color color;
  final Color? border;
  const Panel({super.key, required this.child, this.padding = const EdgeInsets.all(12), this.color = C.card, this.border});
  @override
  Widget build(BuildContext context) => Container(
        padding: padding,
        decoration: BoxDecoration(
          color: color,
          borderRadius: BorderRadius.circular(16),
          border: border == null ? null : Border.all(color: border!.withOpacity(.45)),
        ),
        child: child,
      );
}

void toast(BuildContext context, String text, {Color color = C.card2}) {
  ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(content: Text(text), backgroundColor: color, behavior: SnackBarBehavior.floating));
}
