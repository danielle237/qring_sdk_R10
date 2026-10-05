import 'package:flutter/material.dart';

import '../api.dart';
import '../i18n.dart';
import '../main.dart';
import '../widgets.dart';

/// Historique du sommeil : une barre par nuit (profond · léger · paradoxal · éveillé), 7 ou 30 nuits.
/// Les nuits viennent de la base (la GATEWAY RHM les envoie chaque matin).
class SleepScreen extends StatefulWidget {
  final String mac;
  const SleepScreen({super.key, required this.mac});
  @override
  State<SleepScreen> createState() => _SleepScreenState();
}

const _cDeep = Color(0xFF5B6CFF);
const _cLight = Color(0xFF8FA8FF);
const _cRem = Color(0xFFB18CFF);
const _cAwake = Color(0xFFFFB84D);

String _hm(int minutes) => '${minutes ~/ 60} h ${two(minutes % 60)}';

class _SleepScreenState extends State<SleepScreen> {
  int days = 30;
  bool loading = true;
  String? error;
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
      final res = await m.api.sleep(r.key, days);
      nights = (res['nights'] as List).map((x) => Map<String, dynamic>.from(x as Map)).toList();
    } on ApiException catch (e) {
      error = e.message;
      nights = [];
    } catch (_) {
      error = tr('err.network');
      nights = [];
    }
    if (mounted) setState(() => loading = false);
  }

  int _i(Map n, String k) => ((n[k] as num?) ?? 0).toInt();

  @override
  Widget build(BuildContext context) {
    final m = ModelScope.of(context);
    final r = m.ringByMac(widget.mac);
    final maxTotal = nights.fold<int>(1, (a, n) => _i(n, 'total') > a ? _i(n, 'total') : a);
    final avg = nights.isEmpty ? 0 : nights.fold<int>(0, (a, n) => a + _i(n, 'total')) ~/ nights.length;

    Widget legend(Color c, String t) => Row(mainAxisSize: MainAxisSize.min, children: [
          Container(width: 10, height: 10, decoration: BoxDecoration(color: c, borderRadius: BorderRadius.circular(3))),
          const SizedBox(width: 4),
          Text(t, style: const TextStyle(color: C.muted, fontSize: 12)),
        ]);

    return Scaffold(
      appBar: AppBar(title: Text('${tr('sl.title')} · ${r?.title ?? ''}')),
      body: RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(14, 4, 14, 24),
          children: [
            Wrap(spacing: 6, children: [
              ChoiceChip(label: Text(tr('hist.7d')), selected: days == 7, onSelected: (_) { days = 7; _load(); }),
              ChoiceChip(label: Text(tr('hist.30d')), selected: days == 30, onSelected: (_) { days = 30; _load(); }),
            ]),
            const SizedBox(height: 10),
            Wrap(spacing: 12, runSpacing: 4, children: [
              legend(_cDeep, tr('sl.deep')),
              legend(_cLight, tr('sl.light')),
              legend(_cRem, tr('sl.rem')),
              legend(_cAwake, tr('sl.awake')),
            ]),
            const SizedBox(height: 10),
            if (loading)
              const Padding(padding: EdgeInsets.only(top: 60), child: Center(child: CircularProgressIndicator()))
            else if (error != null)
              Padding(padding: const EdgeInsets.only(top: 40), child: Text(error!, textAlign: TextAlign.center, style: const TextStyle(color: C.err)))
            else if (nights.isEmpty)
              Padding(padding: const EdgeInsets.only(top: 40), child: Text(tr('sl.none'), textAlign: TextAlign.center, style: const TextStyle(color: C.muted)))
            else ...[
              Panel(child: Text(tr('sl.avg', [_hm(avg), nights.length]), style: const TextStyle(fontWeight: FontWeight.w700))),
              const SizedBox(height: 10),
              // Une ligne par nuit : date, barre empilée, durée totale
              for (final n in nights)
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: Panel(
                    padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Row(children: [
                        Expanded(
                          child: Text(_dateLabel(n['date'] as String? ?? ''),
                              style: const TextStyle(fontWeight: FontWeight.w700)),
                        ),
                        Text(_hm(_i(n, 'total')), style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 16)),
                      ]),
                      if (n['start'] != null && n['end'] != null)
                        Text(tr('sl.bed', [hm(_i(n, 'start')), hm(_i(n, 'end'))]),
                            style: const TextStyle(color: C.muted, fontSize: 12)),
                      const SizedBox(height: 6),
                      LayoutBuilder(builder: (ctx, c) {
                        final w = c.maxWidth * _i(n, 'total') / maxTotal;
                        final parts = [
                          (_i(n, 'deep'), _cDeep),
                          (_i(n, 'light'), _cLight),
                          (_i(n, 'rem'), _cRem),
                          (_i(n, 'awake'), _cAwake),
                        ];
                        final sum = parts.fold<int>(0, (a, p) => a + p.$1);
                        return ClipRRect(
                          borderRadius: BorderRadius.circular(6),
                          child: SizedBox(
                            width: w,
                            height: 14,
                            child: Row(children: [
                              for (final p in parts)
                                if (p.$1 > 0) Expanded(flex: p.$1, child: Container(color: p.$2)),
                              if (sum == 0) Expanded(child: Container(color: C.line)),
                            ]),
                          ),
                        );
                      }),
                      const SizedBox(height: 6),
                      Text(
                        '${tr('sl.deep')} ${_hm(_i(n, 'deep'))} · ${tr('sl.light')} ${_hm(_i(n, 'light'))} · '
                        '${tr('sl.rem')} ${_hm(_i(n, 'rem'))} · ${tr('sl.awake')} ${_hm(_i(n, 'awake'))}',
                        style: const TextStyle(color: C.muted, fontSize: 12),
                      ),
                    ]),
                  ),
                ),
            ],
          ],
        ),
      ),
    );
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
}
