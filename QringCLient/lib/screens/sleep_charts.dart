import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../api.dart';
import '../i18n.dart';
import '../main.dart';
import '../widgets.dart';

/// « Sommeil graphique » (comme l'app QRing) : Jour (hypnogramme + stades + mesures de la nuit),
/// Semaine, Mois, Année (moyenne par nuit, mois par mois). Les nuits viennent de la base.
class SleepChartsScreen extends StatefulWidget {
  final String mac;
  const SleepChartsScreen({super.key, required this.mac});
  @override
  State<SleepChartsScreen> createState() => _SleepChartsScreenState();
}

const _cDeep = Color(0xFF5B6CFF);
const _cLight = Color(0xFF8FA8FF);
const _cRem = Color(0xFFB18CFF);
const _cAwake = Color(0xFFFFB84D);

String _hm(int minutes) => '${minutes ~/ 60} h ${two(minutes % 60)}';
int _i(Map n, String k) => ((n[k] as num?) ?? 0).toInt();

Color _phaseColor(String t) => switch (t) {
      'deep' => _cDeep,
      'light' => _cLight,
      'rem' => _cRem,
      'awake' => _cAwake,
      _ => C.line,
    };

String _phaseName(String t) => switch (t) {
      'deep' => tr('sl.deep'),
      'light' => tr('sl.light'),
      'rem' => tr('sl.rem'),
      'awake' => tr('sl.awake'),
      _ => '—',
    };

/// Niveau dans l'hypnogramme : éveil en haut, profond en bas.
int _phaseLevel(String t) => switch (t) {
      'awake' => 0,
      'rem' => 1,
      'light' => 2,
      'deep' => 3,
      _ => 2,
    };

class _SleepChartsScreenState extends State<SleepChartsScreen> {
  bool loading = true;
  String? error;
  /// Nuits de l'année, de la plus ancienne à la plus récente (sans les phases)
  List<Map<String, dynamic>> nights = [];

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final m = ModelScope.read(context);
    final r = m.ringByMac(widget.mac);
    if (r == null) return;
    setState(() {
      loading = true;
      error = null;
    });
    try {
      final res = await m.api.sleepAll(r.key, 370);
      nights = (res['nights'] as List).map((x) => Map<String, dynamic>.from(x as Map)).toList()
        ..sort((a, b) => (a['date'] as String).compareTo(b['date'] as String));
    } on ApiException catch (e) {
      error = e.message;
      nights = [];
    } catch (_) {
      error = tr('err.network');
      nights = [];
    }
    if (mounted) setState(() => loading = false);
  }

  @override
  Widget build(BuildContext context) {
    final m = ModelScope.of(context);
    final r = m.ringByMac(widget.mac);
    return DefaultTabController(
      length: 4,
      child: Scaffold(
        appBar: AppBar(
          title: Text('${tr('slg.title')} · ${r?.title ?? ''}'),
          bottom: TabBar(tabs: [
            Tab(text: tr('slg.day')),
            Tab(text: tr('slg.week')),
            Tab(text: tr('slg.month')),
            Tab(text: tr('slg.year')),
          ]),
        ),
        body: loading
            ? const Center(child: CircularProgressIndicator())
            : error != null
                ? Center(child: Text(error!, style: const TextStyle(color: C.err)))
                : nights.isEmpty
                    ? Center(child: Text(tr('sl.none'), style: const TextStyle(color: C.muted)))
                    : TabBarView(children: [
                        _DayTab(mac: widget.mac, nights: nights),
                        _PeriodTab(nights: nights, days: 7),
                        _PeriodTab(nights: nights, days: 30),
                        _YearTab(nights: nights),
                      ]),
      ),
    );
  }
}

// ============================================================================ Légende

Widget _legend() {
  Widget item(Color c, String t) => Row(mainAxisSize: MainAxisSize.min, children: [
        Container(width: 10, height: 10, decoration: BoxDecoration(color: c, borderRadius: BorderRadius.circular(3))),
        const SizedBox(width: 4),
        Text(t, style: const TextStyle(color: C.muted, fontSize: 12)),
      ]);
  return Wrap(spacing: 12, runSpacing: 4, children: [
    item(_cDeep, tr('sl.deep')),
    item(_cLight, tr('sl.light')),
    item(_cRem, tr('sl.rem')),
    item(_cAwake, tr('sl.awake')),
  ]);
}

/// « lun. 29/09 » à partir de « 2026-09-29 »
String _dateLabel(String iso) {
  final d = DateTime.tryParse(iso);
  if (d == null) return iso;
  const fr = ['lun.', 'mar.', 'mer.', 'jeu.', 'ven.', 'sam.', 'dim.'];
  const en = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  const ar = ['الإثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة', 'السبت', 'الأحد'];
  final names = appLang == 'en' ? en : appLang == 'ar' ? ar : fr;
  return '${names[d.weekday - 1]} ${two(d.day)}/${two(d.month)}';
}

String _monthShort(int month) {
  const fr = ['jan', 'fév', 'mar', 'avr', 'mai', 'juin', 'juil', 'aoû', 'sep', 'oct', 'nov', 'déc'];
  const en = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const ar = ['ينا', 'فبر', 'مار', 'أبر', 'ماي', 'يون', 'يول', 'أغس', 'سبت', 'أكت', 'نوف', 'ديس'];
  final names = appLang == 'en' ? en : appLang == 'ar' ? ar : fr;
  return names[(month - 1) % 12];
}

// ============================================================================ Jour

class _DayTab extends StatefulWidget {
  final String mac;
  final List<Map<String, dynamic>> nights;
  const _DayTab({required this.mac, required this.nights});
  @override
  State<_DayTab> createState() => _DayTabState();
}

class _DayTabState extends State<_DayTab> with AutomaticKeepAliveClientMixin {
  late int index = widget.nights.length - 1;
  bool loading = false;
  String? error;
  Map<String, dynamic>? night;
  Map<String, dynamic> vitals = {};
  Map<String, dynamic>? picked; // phase touchée dans l'hypnogramme

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final m = ModelScope.read(context);
    final r = m.ringByMac(widget.mac);
    if (r == null) return;
    setState(() {
      loading = true;
      error = null;
      picked = null;
      night = null;
      vitals = {};
    });
    try {
      final res = await m.api.sleepNight(r.key, widget.nights[index]['date'] as String);
      night = Map<String, dynamic>.from(res['night'] as Map);
      vitals = Map<String, dynamic>.from((res['vitals'] ?? {}) as Map);
    } on ApiException catch (e) {
      error = e.message;
    } catch (_) {
      error = tr('err.network');
    }
    if (mounted) setState(() => loading = false);
  }

  void _go(int delta) {
    final i = index + delta;
    if (i < 0 || i >= widget.nights.length) return;
    index = i;
    _load();
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final n = night ?? widget.nights[index];
    final total = _i(n, 'total');
    final awake = _i(n, 'awake');
    final eff = total > 0 ? ((total - awake) * 100 / total).round() : 0;
    final phases = ((n['phases'] as List?) ?? const [])
        .map((x) => Map<String, dynamic>.from(x as Map))
        .where((p) => p['start'] is num && p['end'] is num)
        .toList();

    return ListView(
      padding: const EdgeInsets.fromLTRB(14, 10, 14, 24),
      children: [
        // Navigation entre les nuits
        Row(children: [
          IconButton(onPressed: index > 0 ? () => _go(-1) : null, icon: const Icon(Icons.chevron_left)),
          Expanded(
            child: Text(_dateLabel(n['date'] as String? ?? ''),
                textAlign: TextAlign.center, style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 16)),
          ),
          IconButton(
              onPressed: index < widget.nights.length - 1 ? () => _go(1) : null, icon: const Icon(Icons.chevron_right)),
        ]),
        if (loading) const LinearProgressIndicator(),
        if (error != null) Text(error!, style: const TextStyle(color: C.err)),
        const SizedBox(height: 8),
        // Résumé : durée totale, coucher – lever, efficacité
        Panel(
          child: Row(children: [
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(tr('slg.total'), style: const TextStyle(color: C.muted, fontSize: 12)),
                Text(_hm(total), style: const TextStyle(fontSize: 26, fontWeight: FontWeight.w800)),
                if (n['start'] != null && n['end'] != null)
                  Text('${hm(_i(n, 'start'))} – ${hm(_i(n, 'end'))}', style: const TextStyle(color: C.muted)),
              ]),
            ),
            SizedBox(
              width: 76,
              height: 76,
              child: Stack(alignment: Alignment.center, children: [
                SizedBox(
                  width: 76,
                  height: 76,
                  child: CircularProgressIndicator(
                      value: eff / 100, strokeWidth: 7, backgroundColor: C.line, color: eff >= 85 ? C.ok : C.warn),
                ),
                Column(mainAxisSize: MainAxisSize.min, children: [
                  Text('$eff %', style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 16)),
                  Text(tr('slg.eff'), style: const TextStyle(color: C.muted, fontSize: 10)),
                ]),
              ]),
            ),
          ]),
        ),
        const SizedBox(height: 10),
        // Hypnogramme (touchable)
        Panel(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            _legend(),
            const SizedBox(height: 10),
            if (phases.isEmpty)
              Text(tr('slg.no_phases'), style: const TextStyle(color: C.muted))
            else ...[
              _Hypnogram(phases: phases, onPick: (p) => setState(() => picked = p), picked: picked),
              const SizedBox(height: 6),
              Text(
                picked == null
                    ? tr('slg.tap')
                    : '${_phaseName(picked!['type'] as String? ?? '')} · '
                        '${((_ts(picked!['end']) - _ts(picked!['start'])) / 60).round()} min · '
                        '${hm(_ts(picked!['start']))} – ${hm(_ts(picked!['end']))}',
                style: TextStyle(
                    color: picked == null ? C.muted : _phaseColor(picked!['type'] as String? ?? ''),
                    fontWeight: picked == null ? FontWeight.w400 : FontWeight.w700),
              ),
            ],
          ]),
        ),
        const SizedBox(height: 10),
        // Stades : minutes et %
        Panel(
          child: Column(children: [
            for (final s in const ['awake', 'rem', 'light', 'deep'])
              _StageBar(
                label: _phaseName(s),
                minutes: _i(n, s),
                total: total,
                color: _phaseColor(s),
              ),
          ]),
        ),
        // Mesures enregistrées pendant la nuit
        if (vitals.isNotEmpty) ...[
          const SizedBox(height: 14),
          Text(tr('slg.vitals'), style: const TextStyle(fontWeight: FontWeight.w800)),
          const SizedBox(height: 6),
          for (final k in const ['hr', 'spo2', 'hrv', 'temp'])
            if (vitals[k] != null)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: _VitalCard(kind: k, data: Map<String, dynamic>.from(vitals[k] as Map)),
              ),
        ],
      ],
    );
  }
}

/// Heure Unix (secondes) ; les valeurs en millisecondes sont converties.
int _ts(dynamic v) {
  final x = (v as num).toInt();
  return x > 100000000000 ? x ~/ 1000 : x;
}

class _Hypnogram extends StatelessWidget {
  final List<Map<String, dynamic>> phases;
  final Map<String, dynamic>? picked;
  final ValueChanged<Map<String, dynamic>> onPick;
  const _Hypnogram({required this.phases, required this.onPick, this.picked});

  @override
  Widget build(BuildContext context) {
    final t0 = phases.map((p) => _ts(p['start'])).reduce(math.min);
    final t1 = phases.map((p) => _ts(p['end'])).reduce(math.max);
    return Column(children: [
      LayoutBuilder(builder: (ctx, c) {
        final w = c.maxWidth;
        return GestureDetector(
          onTapDown: (d) {
            final t = t0 + (d.localPosition.dx / w) * (t1 - t0);
            for (final p in phases) {
              if (t >= _ts(p['start']) && t <= _ts(p['end'])) {
                onPick(p);
                return;
              }
            }
          },
          child: CustomPaint(
            size: Size(w, 140),
            painter: _HypnoPainter(phases, t0, t1, picked),
          ),
        );
      }),
      const SizedBox(height: 4),
      Row(children: [
        Text(hm(t0), style: const TextStyle(color: C.muted, fontSize: 11)),
        const Spacer(),
        Text(hm(t1), style: const TextStyle(color: C.muted, fontSize: 11)),
      ]),
    ]);
  }
}

class _HypnoPainter extends CustomPainter {
  final List<Map<String, dynamic>> phases;
  final int t0, t1;
  final Map<String, dynamic>? picked;
  _HypnoPainter(this.phases, this.t0, this.t1, this.picked);

  @override
  void paint(Canvas canvas, Size size) {
    final span = math.max(1, t1 - t0);
    final rowH = size.height / 4;
    final grid = Paint()
      ..color = C.line
      ..strokeWidth = 1;
    for (var i = 1; i < 4; i++) {
      canvas.drawLine(Offset(0, rowH * i), Offset(size.width, rowH * i), grid);
    }
    for (final p in phases) {
      final type = p['type'] as String? ?? '';
      final x0 = (_ts(p['start']) - t0) / span * size.width;
      final x1 = (_ts(p['end']) - t0) / span * size.width;
      final level = _phaseLevel(type);
      final rect = Rect.fromLTRB(x0, rowH * level + 3, math.max(x0 + 1.5, x1), rowH * (level + 1) - 3);
      final paint = Paint()..color = _phaseColor(type).withOpacity(identical(p, picked) || picked == null ? 1.0 : 0.45);
      canvas.drawRRect(RRect.fromRectAndRadius(rect, const Radius.circular(3)), paint);
    }
  }

  @override
  bool shouldRepaint(covariant _HypnoPainter old) => old.picked != picked || old.phases != phases;
}

class _StageBar extends StatelessWidget {
  final String label;
  final int minutes;
  final int total;
  final Color color;
  const _StageBar({required this.label, required this.minutes, required this.total, required this.color});

  @override
  Widget build(BuildContext context) {
    final pct = total > 0 ? (minutes * 100 / total).round() : 0;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 5),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text(label, style: const TextStyle(fontWeight: FontWeight.w600))),
          Text('${_hm(minutes)}  ·  $pct %', style: const TextStyle(color: C.muted)),
        ]),
        const SizedBox(height: 4),
        ClipRRect(
          borderRadius: BorderRadius.circular(6),
          child: LinearProgressIndicator(value: pct / 100, minHeight: 8, color: color, backgroundColor: C.line),
        ),
      ]),
    );
  }
}

class _VitalCard extends StatelessWidget {
  final String kind;
  final Map<String, dynamic> data;
  const _VitalCard({required this.kind, required this.data});

  @override
  Widget build(BuildContext context) {
    final (title, unit, color) = switch (kind) {
      'hr' => (tr('slg.hr'), 'bpm', const Color(0xFFFF5D73)),
      'spo2' => (tr('slg.spo2'), '%', const Color(0xFF4FC3F7)),
      'hrv' => (tr('slg.hrv'), 'ms', const Color(0xFF3ECF8E)),
      _ => (tr('slg.temp'), '°C', const Color(0xFFFFB547)),
    };
    final pts = ((data['points'] as List?) ?? const [])
        .map((p) => (((p as List)[0] as num).toInt(), (p[1] as num).toDouble()))
        .toList();
    return Panel(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text(title, style: const TextStyle(fontWeight: FontWeight.w700))),
          Text('${data['avg']} $unit', style: TextStyle(color: color, fontWeight: FontWeight.w800, fontSize: 16)),
        ]),
        Text(tr('slg.minmax', ['${data['min']}', '${data['max']}', unit]),
            style: const TextStyle(color: C.muted, fontSize: 12)),
        if (pts.length >= 2) ...[
          const SizedBox(height: 8),
          SizedBox(height: 60, width: double.infinity, child: CustomPaint(painter: _LinePainter(pts, color))),
        ],
      ]),
    );
  }
}

class _LinePainter extends CustomPainter {
  final List<(int, double)> pts;
  final Color color;
  _LinePainter(this.pts, this.color);

  @override
  void paint(Canvas canvas, Size size) {
    final t0 = pts.first.$1, t1 = pts.last.$1;
    var lo = pts.map((p) => p.$2).reduce(math.min), hi = pts.map((p) => p.$2).reduce(math.max);
    if (hi - lo < 1) {
      hi += 1;
      lo -= 1;
    }
    final path = Path();
    for (var i = 0; i < pts.length; i++) {
      final x = (pts[i].$1 - t0) / math.max(1, t1 - t0) * size.width;
      final y = size.height - (pts[i].$2 - lo) / (hi - lo) * size.height;
      if (i == 0) {
        path.moveTo(x, y);
      } else {
        path.lineTo(x, y);
      }
    }
    canvas.drawPath(
        path,
        Paint()
          ..color = color
          ..strokeWidth = 2
          ..style = PaintingStyle.stroke);
  }

  @override
  bool shouldRepaint(covariant _LinePainter old) => old.pts != pts;
}

// ============================================================================ Semaine / Mois

/// Une barre empilée par nuit (profond en bas, puis léger, REM, éveil).
class _PeriodTab extends StatefulWidget {
  final List<Map<String, dynamic>> nights;
  final int days;
  const _PeriodTab({required this.nights, required this.days});
  @override
  State<_PeriodTab> createState() => _PeriodTabState();
}

class _PeriodTabState extends State<_PeriodTab> {
  int? pickedDay;

  @override
  Widget build(BuildContext context) {
    final today = DateTime.now();
    final byDate = {for (final n in widget.nights) n['date'] as String: n};
    final days = [
      for (var i = widget.days - 1; i >= 0; i--) today.subtract(Duration(days: i)),
    ];
    String iso(DateTime d) => '${d.year}-${two(d.month)}-${two(d.day)}';
    final list = [for (final d in days) byDate[iso(d)]];
    final have = list.whereType<Map<String, dynamic>>().toList();
    final avg = have.isEmpty ? 0 : have.fold<int>(0, (a, n) => a + _i(n, 'total')) ~/ have.length;
    final maxTotal = math.max(60, list.fold<int>(0, (a, n) => n == null ? a : math.max(a, _i(n, 'total'))));
    final sel = pickedDay != null ? list[pickedDay!] : null;

    return ListView(
      padding: const EdgeInsets.fromLTRB(14, 12, 14, 24),
      children: [
        Panel(
            child: Text(tr('slg.avg_night', [_hm(avg), have.length]),
                style: const TextStyle(fontWeight: FontWeight.w700))),
        const SizedBox(height: 10),
        _legend(),
        const SizedBox(height: 10),
        Panel(
          child: Column(children: [
            SizedBox(
              height: 180,
              child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
                for (var i = 0; i < list.length; i++)
                  Expanded(
                    child: GestureDetector(
                      onTap: () => setState(() => pickedDay = i),
                      child: Padding(
                        padding: EdgeInsets.symmetric(horizontal: widget.days <= 7 ? 6 : 1),
                        child: _StackedBar(night: list[i], maxTotal: maxTotal, highlight: pickedDay == i),
                      ),
                    ),
                  ),
              ]),
            ),
            const SizedBox(height: 6),
            Row(children: [
              for (var i = 0; i < days.length; i++)
                Expanded(
                  child: Text(
                    widget.days <= 7 || i % 5 == 0 || i == days.length - 1 ? '${days[i].day}' : '',
                    textAlign: TextAlign.center,
                    style: const TextStyle(color: C.muted, fontSize: 10),
                  ),
                ),
            ]),
          ]),
        ),
        const SizedBox(height: 10),
        if (pickedDay != null)
          Panel(
            child: Text(
              sel == null
                  ? '${_dateLabel(iso(days[pickedDay!]))} · ${tr('slg.no_night')}'
                  : '${_dateLabel(sel['date'] as String)} · ${_hm(_i(sel, 'total'))}\n'
                      '${tr('sl.deep')} ${_hm(_i(sel, 'deep'))} · ${tr('sl.light')} ${_hm(_i(sel, 'light'))} · '
                      '${tr('sl.rem')} ${_hm(_i(sel, 'rem'))} · ${tr('sl.awake')} ${_hm(_i(sel, 'awake'))}',
            ),
          ),
      ],
    );
  }
}

class _StackedBar extends StatelessWidget {
  final Map<String, dynamic>? night;
  final int maxTotal;
  final bool highlight;
  const _StackedBar({required this.night, required this.maxTotal, this.highlight = false});

  @override
  Widget build(BuildContext context) {
    final n = night;
    if (n == null || _i(n, 'total') == 0) {
      return Container(height: 3, color: C.line);
    }
    return LayoutBuilder(builder: (ctx, c) {
      final h = c.maxHeight * _i(n, 'total') / maxTotal;
      final parts = [
        (_i(n, 'awake'), _cAwake),
        (_i(n, 'rem'), _cRem),
        (_i(n, 'light'), _cLight),
        (_i(n, 'deep'), _cDeep),
      ];
      return Container(
        height: h,
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(4),
          border: highlight ? Border.all(color: C.text, width: 1.5) : null,
        ),
        clipBehavior: Clip.antiAlias,
        child: Column(children: [
          for (final p in parts)
            if (p.$1 > 0) Expanded(flex: p.$1, child: Container(color: p.$2)),
        ]),
      );
    });
  }
}

// ============================================================================ Année

/// 12 derniers mois : pour chaque mois, la moyenne par nuit (stades empilés).
class _YearTab extends StatefulWidget {
  final List<Map<String, dynamic>> nights;
  const _YearTab({required this.nights});
  @override
  State<_YearTab> createState() => _YearTabState();
}

class _YearTabState extends State<_YearTab> {
  int? picked;

  @override
  Widget build(BuildContext context) {
    final now = DateTime.now();
    final months = [for (var i = 11; i >= 0; i--) DateTime(now.year, now.month - i, 1)];
    final avgs = <Map<String, dynamic>?>[];
    for (final mo in months) {
      final inMonth = widget.nights.where((n) {
        final d = DateTime.tryParse(n['date'] as String? ?? '');
        return d != null && d.year == mo.year && d.month == mo.month && _i(n, 'total') > 0;
      }).toList();
      if (inMonth.isEmpty) {
        avgs.add(null);
        continue;
      }
      int avg(String k) => inMonth.fold<int>(0, (a, n) => a + _i(n, k)) ~/ inMonth.length;
      avgs.add({
        'total': avg('total'),
        'deep': avg('deep'),
        'light': avg('light'),
        'rem': avg('rem'),
        'awake': avg('awake'),
        'count': inMonth.length,
      });
    }
    final have = avgs.whereType<Map<String, dynamic>>().toList();
    final allNights = have.fold<int>(0, (a, m) => a + (m['count'] as int));
    final yearAvg = allNights == 0
        ? 0
        : have.fold<int>(0, (a, m) => a + (m['total'] as int) * (m['count'] as int)) ~/ allNights;
    final maxTotal = math.max(60, have.fold<int>(0, (a, m) => math.max(a, m['total'] as int)));
    final sel = picked != null ? avgs[picked!] : null;

    return ListView(
      padding: const EdgeInsets.fromLTRB(14, 12, 14, 24),
      children: [
        Panel(
            child: Text(tr('slg.avg_night', [_hm(yearAvg), allNights]),
                style: const TextStyle(fontWeight: FontWeight.w700))),
        const SizedBox(height: 10),
        _legend(),
        const SizedBox(height: 10),
        Panel(
          child: Column(children: [
            SizedBox(
              height: 200,
              child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
                for (var i = 0; i < months.length; i++)
                  Expanded(
                    child: GestureDetector(
                      onTap: () => setState(() => picked = i),
                      child: Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 3),
                        child: _StackedBar(night: avgs[i], maxTotal: maxTotal, highlight: picked == i),
                      ),
                    ),
                  ),
              ]),
            ),
            const SizedBox(height: 6),
            Row(children: [
              for (final mo in months)
                Expanded(
                  child: Text(_monthShort(mo.month),
                      textAlign: TextAlign.center, style: const TextStyle(color: C.muted, fontSize: 10)),
                ),
            ]),
          ]),
        ),
        const SizedBox(height: 10),
        if (picked != null)
          Panel(
            child: Text(
              sel == null
                  ? '${_monthShort(months[picked!].month)} ${months[picked!].year} · ${tr('slg.no_night')}'
                  : '${_monthShort(months[picked!].month)} ${months[picked!].year} · '
                      '${tr('slg.avg_night', [_hm(sel['total'] as int), sel['count']])}\n'
                      '${tr('sl.deep')} ${_hm(sel['deep'] as int)} · ${tr('sl.light')} ${_hm(sel['light'] as int)} · '
                      '${tr('sl.rem')} ${_hm(sel['rem'] as int)} · ${tr('sl.awake')} ${_hm(sel['awake'] as int)}',
            ),
          ),
      ],
    );
  }
}
