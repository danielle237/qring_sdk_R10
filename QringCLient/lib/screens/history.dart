import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../api.dart';
import '../i18n.dart';
import '../main.dart';
import '../widgets.dart';

/// Historique d'une bague : 24 h / 7 j / 30 j, courbe + liste (mesures en base).
class HistoryScreen extends StatefulWidget {
  final String mac;
  const HistoryScreen({super.key, required this.mac});
  @override
  State<HistoryScreen> createState() => _HistoryScreenState();
}

class _HistoryScreenState extends State<HistoryScreen> {
  String type = 'hr';
  int hours = 24;
  bool loading = true;
  String? error;
  List<Map<String, dynamic>> rows = [];

  @override
  void initState() {
    super.initState();
    final r = ModelScope.read(context).ringByMac(widget.mac);
    final vis = r?.visible ?? const ['hr'];
    type = vis.contains('hr') ? 'hr' : (vis.isNotEmpty ? vis.first : 'hr');
    _load();
  }

  Future<void> _load() async {
    final m = ModelScope.read(context);
    final r = m.ringByMac(widget.mac);
    if (r == null) {
      setState(() => loading = false);
      return;
    }
    setState(() {
      loading = true;
      error = null;
    });
    try {
      final res = await m.api.history(r.key, type, hours);
      rows = (res['rows'] as List).map((x) => Map<String, dynamic>.from(x as Map)).toList();
    } on ApiException catch (e) {
      error = e.message;
      rows = [];
    } catch (_) {
      error = tr('err.network');
      rows = [];
    }
    if (mounted) setState(() => loading = false);
  }

  Widget _chip(String label, bool on, VoidCallback tap) => Padding(
        padding: const EdgeInsetsDirectional.only(end: 6, bottom: 6),
        child: ChoiceChip(label: Text(label), selected: on, onSelected: (_) => tap()),
      );

  @override
  Widget build(BuildContext context) {
    final m = ModelScope.of(context);
    final r = m.ringByMac(widget.mac);
    final vis = (r?.visible ?? const <String>[]).where((k) => metrics.any((x) => x.key == k)).toList();
    final mt = metricOf(type);
    final ok = rows.where((x) => x['status'] == 'ok' && x['value'] != null).toList().reversed.toList();
    final values = ok.map((x) => (x['value'] as num).toDouble()).toList();
    String fmt(double v) => type == 'temp' ? v.toStringAsFixed(1) : v.round().toString();

    return Scaffold(
      appBar: AppBar(title: Text('${tr('ring.history')} · ${r?.label ?? ''}')),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(14, 4, 14, 24),
        children: [
          Wrap(children: [
            _chip(tr('hist.24h'), hours == 24, () { hours = 24; _load(); }),
            _chip(tr('hist.7d'), hours == 168, () { hours = 168; _load(); }),
            _chip(tr('hist.30d'), hours == 720, () { hours = 720; _load(); }),
          ]),
          Wrap(children: [
            for (final k in vis) _chip('${metricOf(k).icon} ${tr('btn.$k')}', type == k, () { type = k; _load(); }),
          ]),
          const SizedBox(height: 6),
          Panel(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('${mt.label} · ${hours == 24 ? tr('hist.24h') : hours == 168 ? tr('hist.7d') : tr('hist.30d')}',
                  style: const TextStyle(color: C.muted, fontSize: 12)),
              const SizedBox(height: 10),
              SizedBox(
                height: 160,
                child: loading
                    ? const Center(child: CircularProgressIndicator())
                    : values.isEmpty
                        ? Center(child: Text(error ?? tr('hist.none'), style: const TextStyle(color: C.muted)))
                        : CustomPaint(size: Size.infinite, painter: _Chart(values, mt.color)),
              ),
              if (values.isNotEmpty) ...[
                const SizedBox(height: 8),
                Text(
                  tr('hist.stats', [
                    fmt(values.reduce((a, b) => a + b) / values.length),
                    fmt(values.reduce(math.min)),
                    fmt(values.reduce(math.max)),
                  ]),
                  style: const TextStyle(color: C.muted, fontSize: 12),
                ),
              ],
            ]),
          ),
          const SizedBox(height: 10),
          for (final x in rows.take(200)) _Row(x, type),
        ],
      ),
    );
  }
}

class _Row extends StatelessWidget {
  final Map<String, dynamic> x;
  final String type;
  const _Row(this.x, this.type);
  @override
  Widget build(BuildContext context) {
    final ts = ((x['ts'] as num?) ?? 0).toInt();
    final okRow = x['status'] == 'ok' && x['value'] != null;
    final mt = metricOf(type);
    String value;
    if (!okRow) {
      value = tr('err.${x['reason'] == 'device_out_of_range' ? 'ring_disconnected' : x['reason'] ?? 'measure_failed'}');
    } else if (type == 'bp') {
      value = '${(x['value'] as num).round()}/${x['dbp'] ?? '--'} ${mt.unit}';
    } else {
      value = '${formatValue(type, {'value': x['value'], 'steps': x['value']})} ${mt.unit}';
    }
    final dur = (x['dur'] as num?)?.toInt();
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Panel(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        child: Row(children: [
          SizedBox(width: 92, child: Text(dayHm(ts), style: const TextStyle(fontSize: 13))),
          Expanded(
            child: Text(value,
                style: TextStyle(fontWeight: FontWeight.w700, color: okRow ? C.text : C.warn, fontSize: 14)),
          ),
          Text(
            [if (dur != null && dur > 0) tr('ring.duration', [dur]), sourceLabel(x['source'] as String?, x['by'] as String?)]
                .where((e) => e.isNotEmpty)
                .join(' · '),
            style: const TextStyle(color: C.muted, fontSize: 11),
          ),
        ]),
      ),
    );
  }
}

class _Chart extends CustomPainter {
  final List<double> v;
  final Color color;
  _Chart(this.v, this.color);

  @override
  void paint(Canvas canvas, Size size) {
    final grid = Paint()
      ..color = C.line
      ..strokeWidth = 1;
    for (var i = 0; i <= 3; i++) {
      final y = size.height * i / 3;
      canvas.drawLine(Offset(0, y), Offset(size.width, y), grid);
    }
    var lo = v.reduce(math.min), hi = v.reduce(math.max);
    if (hi - lo < 1) {
      lo -= 1;
      hi += 1;
    }
    final pad = (hi - lo) * .1;
    lo -= pad;
    hi += pad;
    double px(int i) => v.length == 1 ? size.width / 2 : i * size.width / (v.length - 1);
    double py(double y) => size.height - (y - lo) / (hi - lo) * size.height;
    final line = Path();
    final fill = Path();
    for (var i = 0; i < v.length; i++) {
      if (i == 0) {
        line.moveTo(px(i), py(v[i]));
        fill.moveTo(px(i), size.height);
        fill.lineTo(px(i), py(v[i]));
      } else {
        line.lineTo(px(i), py(v[i]));
        fill.lineTo(px(i), py(v[i]));
      }
    }
    fill.lineTo(px(v.length - 1), size.height);
    fill.close();
    canvas.drawPath(fill, Paint()..color = color.withOpacity(.13));
    canvas.drawPath(
        line,
        Paint()
          ..color = color
          ..style = PaintingStyle.stroke
          ..strokeWidth = 3
          ..strokeCap = StrokeCap.round);
    canvas.drawCircle(Offset(px(v.length - 1), py(v.last)), 4.5, Paint()..color = color);
  }

  @override
  bool shouldRepaint(covariant _Chart old) => old.v != v || old.color != color;
}
