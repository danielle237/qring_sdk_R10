import 'dart:async';

import 'package:flutter/material.dart';

import '../api.dart';
import '../i18n.dart';
import '../main.dart';
import '../model.dart';
import '../v2.dart';
import '../widgets.dart';
import 'history.dart';

enum _St { todo, active, done, failed }

/// V2 · écrans 3 et 4 : « Mesure en cours » (étapes en direct) puis « Mesure terminée ».
/// [follow] : suit une mesure déjà lancée (par ce compte ou un autre) sans en relancer une.
class MeasureScreen extends StatefulWidget {
  final String mac;
  final String cmd;
  final bool follow;
  const MeasureScreen({super.key, required this.mac, required this.cmd, this.follow = false});
  @override
  State<MeasureScreen> createState() => _MeasureScreenState();
}

class _MeasureScreenState extends State<MeasureScreen> {
  int started = 0;
  bool sent = false;
  String? sendError;
  String? gateway;
  String? waitMsg;
  int? finishedAt;
  bool cancelling = false;
  bool trendAsked = false;
  /// Retour automatique au détail du résident quelques secondes après « Mesure réussie »
  Timer? _home;
  static const kHomeDelay = 4;

  @override
  void dispose() {
    _home?.cancel();
    super.dispose();
  }

  void _goHome() {
    _home?.cancel();
    // La mesure est lancée depuis le détail du résident : on y revient (nouvelles valeurs affichées)
    if (mounted && Navigator.of(context).canPop()) Navigator.of(context).pop();
  }

  /// Durée estimée (réglage de l'admin, « measureSeconds »), par défaut 2 min pour « all »
  int _estimate(RingItem r) {
    final m = r.live['measureSeconds'] as Map?;
    final v = (m?[widget.cmd] as num?)?.toInt();
    return v ?? (widget.cmd == 'all' ? 120 : 40);
  }
  final Map<String, List<double>> trend = {};

  /// « all » sur Gateway Linux = HR → SpO₂ → T° → HRV (colmi_4_mesures_v3_clean.py) ; TV = HR + SpO₂
  bool four = true;
  List<String> get keys =>
      widget.cmd == 'all' ? (four ? const ['hr', 'spo2', 'temp', 'hrv'] : const ['hr', 'spo2']) : [widget.cmd];

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => widget.follow ? _attach() : _launch());
  }

  void _attach() {
    final m = ModelScope.read(context);
    final r = m.ringByMac(widget.mac);
    final p = r?.pending[widget.cmd] as Map?;
    setState(() {
      started = ((p?['requested'] ?? p?['since']) as num?)?.toInt() ?? m.serverNow();
      sent = true;
    });
  }

  Future<void> _launch() async {
    final m = ModelScope.read(context);
    final r = m.ringByMac(widget.mac);
    if (r == null) return;
    _home?.cancel();
    _home = null;
    setState(() {
      started = m.serverNow() - 1;
      sent = false;
      sendError = null;
      finishedAt = null;
      trendAsked = false;
      trend.clear();
      waitMsg = null;
    });
    try {
      final res = await m.measureRaw(r, widget.cmd);
      if (!mounted) return;
      setState(() {
        sent = true;
        gateway = res['gateway'] as String?;
        waitMsg = res['message'] as String?;
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      if (e.status == 409 && e.body?['waiting'] == true) {
        // Bague occupée par la mesure d'un autre compte : on patiente, l'app préviendra à la fin
        await showDialog(
          context: context,
          builder: (ctx) => AlertDialog(
            backgroundColor: C.card,
            icon: const Icon(Icons.hourglass_top, color: V2.orange, size: 42),
            title: Text(tr('pop.busy_title'), textAlign: TextAlign.center),
            content: Text('${e.body?['error'] ?? e.message}\n\n${tr('v2.wait_notice')}', textAlign: TextAlign.center),
            actions: [TextButton(onPressed: () => Navigator.pop(ctx), child: Text(tr('btn.ok')))],
          ),
        );
        if (mounted) Navigator.pop(context);
        return;
      }
      setState(() => sendError = e.message);
    }
  }

  Future<void> _cancel(RingItem r) async {
    setState(() => cancelling = true);
    try {
      await ModelScope.read(context).cancelMeasure(r);
      if (mounted) {
        toast(context, tr('v2.cancelled'));
        Navigator.pop(context);
      }
    } on ApiException catch (e) {
      if (mounted) {
        setState(() => cancelling = false);
        toast(context, e.message, color: C.err);
      }
    }
  }

  int _valueTs(RingItem r, String k) {
    final t = (((r.values[k] as Map?)?['ts']) as num?)?.toInt() ?? 0;
    return k == 'battery' && r.batteryTs > t ? r.batteryTs : t;
  }

  bool _done(RingItem r, String k) => started > 0 && _valueTs(r, k) >= started - 1;

  /// Code d'erreur arrivé depuis le lancement (mesure demandée ou une de ses valeurs)
  String? _error(RingItem r) {
    for (final k in {widget.cmd, ...keys}) {
      final e = r.errors[k] as Map?;
      if (e != null && (((e['ts'] as num?) ?? 0).toInt()) >= started - 1) return '${e['code']}';
    }
    return null;
  }

  Future<void> _loadTrend(RingItem r) async {
    if (!r.canHistory) return;
    final api = ModelScope.read(context).api;
    for (final k in keys) {
      if (k == 'battery' || trend.containsKey(k)) continue;
      trend[k] = const [];
      try {
        final res = await api.history(r.key, k, 24);
        final rows = (res['rows'] as List).map((x) => Map<String, dynamic>.from(x as Map));
        final v = rows
            .where((x) => x['status'] == 'ok' && x['value'] != null)
            .take(12)
            .map((x) => (x['value'] as num).toDouble())
            .toList()
            .reversed
            .toList();
        if (mounted) setState(() => trend[k] = v);
      } catch (_) {}
    }
  }

  @override
  Widget build(BuildContext context) {
    final m = ModelScope.of(context);
    final r = m.ringByMac(widget.mac);
    if (r == null) return Scaffold(appBar: AppBar());
    four = r.isLinux;
    return Every(builder: (context) {
      final now = m.serverNow();
      final allDone = keys.every((k) => _done(r, k));
      final anyDone = keys.any((k) => _done(r, k));
      final pend = r.pending[widget.cmd] as Map?;
      final stillPending = r.pending.containsKey(widget.cmd) || keys.any((k) => r.pending.containsKey(k));
      final err = _error(r);
      final limit = widget.cmd == 'all' ? 200 : 140;
      final finished = sent && (allDone || (anyDone && !stillPending && now - started > 3));
      if (finished) {
        finishedAt ??= now;
        _home ??= Timer(const Duration(seconds: kHomeDelay), _goHome);
        if (!trendAsked) {
          trendAsked = true;
          WidgetsBinding.instance.addPostFrameCallback((_) => _loadTrend(r));
        }
        return _result(context, r, now);
      }
      String? failure = sendError;
      if (failure == null && err != null && !anyDone && !(stillPending && err == 'ring_disconnected')) {
        failure = err == 'cancelled' ? tr('v2.cancelled') : tr('err.$err');
      }
      if (failure == null && sent && started > 0 && now - started > limit) failure = tr('v2.timeout');
      if (failure != null) {
        // Échec (bague retirée, hors portée…) : message affiché quelques secondes, puis retour
        // automatique à la fiche du résident, comme après une mesure réussie
        finishedAt ??= now;
        _home ??= Timer(const Duration(seconds: kHomeDelay), _goHome);
        return _failed(context, r, failure, now);
      }
      return _running(context, r, now, pend);
    });
  }

  // ------------------------------------------------------------------ écran 3 : mesure en cours
  Widget _running(BuildContext context, RingItem r, int now, Map? pend) {
    final confirmed = pend?['confirmed'] == true || keys.any((k) => (r.pending[k] as Map?)?['confirmed'] == true);
    final connected = confirmed || keys.any((k) => _done(r, k));
    final wait = (pend?['waitFor'] as Map?)?['message'] as String? ?? (connected ? null : waitMsg);
    final loc = r.location;
    final gw = gateway ?? (loc?['gateway'] as String?) ?? (r.live['deviceName'] as String?);
    final steps = <(String, String?, _St, Color?)>[];
    steps.add((
      tr('v2.step_loc'),
      r.zone != null ? tr('v2.step_zone', [r.zone]) : tr('v2.step_loc_sub'),
      sent ? _St.done : _St.active,
      null
    ));
    steps.add((
      connected ? tr('v2.step_conn_ok') : tr('v2.step_conn'),
      wait ?? (gw != null && gw.isNotEmpty ? tr('v2.step_gw', [gw]) : null),
      connected ? _St.done : (sent ? _St.active : _St.todo),
      wait != null && !connected ? V2.orange : null
    ));
    var prevDone = connected;
    for (final k in keys) {
      final done = _done(r, k);
      final label = switch (k) {
        'hr' => tr('v2.step_hr'),
        'spo2' => tr('v2.step_spo2'),
        'temp' => tr('v2.step_temp'),
        'hrv' => tr('v2.step_hrv'),
        'steps' => tr('v2.step_steps'),
        'battery' => tr('v2.step_battery'),
        _ => tr('v2.step_measure', [metricOf(k).label]),
      };
      final v = r.values[k] as Map?;
      final sub = done ? measureText(k, v?['data'] as Map?) : null;
      steps.add((label, sub, done ? _St.done : (prevDone ? _St.active : _St.todo), null));
      prevDone = done;
    }
    steps.add((tr('v2.step_final'), null, _St.todo, null));

    return Scaffold(
      appBar: AppBar(
        centerTitle: true,
        title: Column(children: [
          Text(tr('v2.m_running'), style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 19)),
          Text('${r.resident} (${r.ringId})', style: const TextStyle(color: C.muted, fontSize: 13)),
        ]),
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(18, 8, 18, 24),
        children: [
          _EtaBar(elapsed: started > 0 ? now - started : 0, estimate: _estimate(r)),
          const SizedBox(height: 16),
          for (var i = 0; i < steps.length; i++)
            _StepRow(steps[i].$1, steps[i].$2, steps[i].$3, last: i == steps.length - 1, subColor: steps[i].$4),
          const SizedBox(height: 18),
          const Center(child: RingArt(size: 110, waves: true)),
          const SizedBox(height: 18),
          if (widget.cmd == 'all')
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(color: V2.card, borderRadius: BorderRadius.circular(14)),
              child: Row(children: [
                const Icon(Icons.bluetooth, color: V2.blue, size: 20),
                const SizedBox(width: 8),
                Expanded(child: Text(tr('v2.one_conn'), style: const TextStyle(fontSize: 12.5))),
              ]),
            ),
          const SizedBox(height: 16),
          OutlinedButton.icon(
            onPressed: cancelling ? null : () => _cancel(r),
            icon: const Icon(Icons.stop_rounded, color: V2.red),
            label: Text(tr('v2.cancel'), style: const TextStyle(color: V2.red, fontWeight: FontWeight.w700)),
            style: OutlinedButton.styleFrom(
              padding: const EdgeInsets.symmetric(vertical: 14),
              side: const BorderSide(color: V2.red),
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(26)),
            ),
          ),
        ],
      ),
    );
  }

  // ------------------------------------------------------------------ écran 4 : mesure terminée
  Widget _result(BuildContext context, RingItem r, int now) {
    final measured = keys.where((k) => _done(r, k)).toList();
    final failed = keys.where((k) => !_done(r, k)).toList();
    return Scaffold(
      appBar: AppBar(
        centerTitle: true,
        title: Column(children: [
          Text(tr('v2.m_done'), style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 19)),
          Text('${r.resident} (${r.ringId})', style: const TextStyle(color: C.muted, fontSize: 13)),
        ]),
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
        children: [
          Container(
            padding: const EdgeInsets.symmetric(vertical: 18),
            decoration: BoxDecoration(
              color: V2.green.withOpacity(.08),
              borderRadius: BorderRadius.circular(18),
              border: Border.all(color: V2.green.withOpacity(.8), width: 1.4),
            ),
            child: Column(children: [
              Container(
                width: 56,
                height: 56,
                decoration: const BoxDecoration(color: V2.green, shape: BoxShape.circle),
                child: const Icon(Icons.check_rounded, color: Color(0xFF06201D), size: 38),
              ),
              const SizedBox(height: 10),
              Text(tr('v2.success'),
                  style: const TextStyle(color: V2.green, fontSize: 20, fontWeight: FontWeight.w800)),
              Text(agoV2(now - (finishedAt ?? now)), style: const TextStyle(color: C.muted)),
            ]),
          ),
          const SizedBox(height: 12),
          for (final k in measured) _ResultCard(r, k, trend[k] ?? const []),
          for (final k in failed)
            Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: Text('${metricOf(k).icon} ${metricOf(k).label} : ${_failText(r, k)}',
                  style: const TextStyle(color: V2.orange)),
            ),
          const SizedBox(height: 6),
          Text(tr('v2.now_visible'), textAlign: TextAlign.center, style: const TextStyle(color: C.muted)),
          const SizedBox(height: 6),
          Text(tr('v2.home_in', [(kHomeDelay - (now - (finishedAt ?? now))).clamp(0, kHomeDelay)]),
              textAlign: TextAlign.center, style: const TextStyle(color: V2.teal, fontSize: 12.5)),
          const SizedBox(height: 14),
          FilledButton.icon(
            onPressed: _goHome,
            icon: const Icon(Icons.check),
            label: const Text('OK', style: TextStyle(fontWeight: FontWeight.w800, fontSize: 16)),
            style: FilledButton.styleFrom(
              backgroundColor: V2.teal,
              foregroundColor: const Color(0xFF06201D),
              padding: const EdgeInsets.symmetric(vertical: 14),
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(26)),
            ),
          ),
          if (r.canHistory)
            TextButton(
              onPressed: () {
                _home?.cancel();     // pas de retour automatique : on va à l'historique
                Navigator.of(context).pushReplacement(MaterialPageRoute(builder: (_) => HistoryScreen(mac: r.mac)));
              },
              child: Text('${tr('v2.see_history')}  ›', style: const TextStyle(color: C.text)),
            ),
        ],
      ),
    );
  }

  String _failText(RingItem r, String k) {
    final e = r.errors[k] as Map?;
    if (e != null && (((e['ts'] as num?) ?? 0).toInt()) >= started - 1) return tr('err.${e['code']}');
    return tr('err.no_data');
  }

  // ------------------------------------------------------------------ échec
  Widget _failed(BuildContext context, RingItem r, String text, int now) {
    return Scaffold(
      appBar: AppBar(
        centerTitle: true,
        title: Column(children: [
          Text(tr('v2.m_failed'), style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 19)),
          Text('${r.resident} (${r.ringId})', style: const TextStyle(color: C.muted, fontSize: 13)),
        ]),
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 24, 16, 24),
        children: [
          Container(
            padding: const EdgeInsets.all(20),
            decoration: BoxDecoration(
              color: V2.red.withOpacity(.08),
              borderRadius: BorderRadius.circular(18),
              border: Border.all(color: V2.red.withOpacity(.8), width: 1.4),
            ),
            child: Column(children: [
              const Icon(Icons.error_outline, color: V2.red, size: 52),
              const SizedBox(height: 10),
              Text(text,
                  textAlign: TextAlign.center,
                  style: const TextStyle(color: V2.red, fontSize: 17, fontWeight: FontWeight.w700)),
            ]),
          ),
          const SizedBox(height: 12),
          Text(tr('v2.home_in', [(kHomeDelay - (now - (finishedAt ?? now))).clamp(0, kHomeDelay)]),
              textAlign: TextAlign.center, style: const TextStyle(color: V2.teal, fontSize: 12.5)),
          const SizedBox(height: 14),
          FilledButton(
            onPressed: r.online && r.canTry && r.runningMeasure == null ? _launch : null,
            style: FilledButton.styleFrom(
              backgroundColor: V2.teal,
              foregroundColor: const Color(0xFF06201D),
              padding: const EdgeInsets.symmetric(vertical: 14),
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(26)),
            ),
            child: Text(tr('v2.retry'), style: const TextStyle(fontWeight: FontWeight.w800)),
          ),
          const SizedBox(height: 8),
          TextButton(onPressed: () => Navigator.pop(context), child: Text(tr('v2.back'))),
        ],
      ),
    );
  }
}

/// « Temps estimé ≈ 2 min · encore 1 min 20 s » + barre de progression
class _EtaBar extends StatelessWidget {
  final int elapsed;
  final int estimate;
  const _EtaBar({required this.elapsed, required this.estimate});

  String _dur(int s) {
    if (s < 60) return tr('v2.s', [s]);
    final m = s ~/ 60, r = s % 60;
    return r == 0 ? tr('v2.min', [m]) : '${tr('v2.min', [m])} ${tr('v2.s', [r])}';
  }

  @override
  Widget build(BuildContext context) {
    final left = estimate - elapsed;
    final p = (elapsed / estimate).clamp(0.0, .97);
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(color: V2.card, borderRadius: BorderRadius.circular(14)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(children: [
          const Icon(Icons.timer_outlined, size: 18, color: V2.teal),
          const SizedBox(width: 8),
          Expanded(
            child: Text(tr('v2.eta', [_dur(estimate)]), style: const TextStyle(fontWeight: FontWeight.w700)),
          ),
          Text('${(p * 100).round()} %', style: const TextStyle(color: V2.teal, fontWeight: FontWeight.w700)),
        ]),
        const SizedBox(height: 8),
        ClipRRect(
          borderRadius: BorderRadius.circular(6),
          child: LinearProgressIndicator(value: p, minHeight: 8, color: V2.teal, backgroundColor: C.line),
        ),
        const SizedBox(height: 6),
        Text(left > 0 ? tr('v2.eta_left', [_dur(left)]) : tr('v2.eta_almost'),
            style: const TextStyle(color: C.muted, fontSize: 12.5)),
      ]),
    );
  }
}

class _StepRow extends StatelessWidget {
  final String title;
  final String? sub;
  final _St st;
  final bool last;
  final Color? subColor;
  const _StepRow(this.title, this.sub, this.st, {this.last = false, this.subColor});

  @override
  Widget build(BuildContext context) {
    Widget icon;
    switch (st) {
      case _St.done:
        icon = Container(
          width: 26,
          height: 26,
          decoration: const BoxDecoration(color: V2.teal, shape: BoxShape.circle),
          child: const Icon(Icons.check, size: 18, color: Color(0xFF06201D)),
        );
      case _St.active:
        icon = const SizedBox(
            width: 26, height: 26, child: CircularProgressIndicator(strokeWidth: 3, color: V2.blue));
      case _St.failed:
        icon = const Icon(Icons.close, color: V2.red, size: 26);
      case _St.todo:
        icon = const SizedBox(width: 26, height: 26, child: Icon(Icons.hourglass_empty, color: C.muted, size: 22));
    }
    final titleColor = st == _St.active ? V2.blue : st == _St.done ? C.text : C.muted;
    return IntrinsicHeight(
      child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Column(children: [
          icon,
          if (!last)
            Expanded(
              child: Container(
                  width: 2, margin: const EdgeInsets.symmetric(vertical: 3), color: st == _St.done ? V2.teal : C.line),
            ),
        ]),
        const SizedBox(width: 12),
        Expanded(
          child: Padding(
            padding: const EdgeInsets.only(bottom: 18, top: 2),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(title,
                  style: TextStyle(
                      color: titleColor, fontSize: 15, fontWeight: st == _St.todo ? FontWeight.w500 : FontWeight.w700)),
              if (sub != null) Text(sub!, style: TextStyle(color: subColor ?? C.muted, fontSize: 12.5)),
            ]),
          ),
        ),
      ]),
    );
  }
}

class _ResultCard extends StatelessWidget {
  final RingItem r;
  final String k;
  final List<double> trend;
  const _ResultCard(this.r, this.k, this.trend);
  @override
  Widget build(BuildContext context) {
    final mt = metricOf(k);
    final v = r.values[k] as Map?;
    final data = v?['data'] as Map?;
    final ts = ((v?['ts'] as num?) ?? 0).toInt();
    final normal = isNormal(k, data?['value'] as num?);
    final unit = k == 'stress' ? '/ 100' : (k == 'battery' ? '%' : mt.unit);
    final value = k == 'battery' ? '${r.battery ?? '--'}' : formatValue(k, data);
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
            color: V2.card, borderRadius: BorderRadius.circular(16), border: Border.all(color: C.line.withOpacity(.6))),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Text(k == 'battery' ? '🔋' : mt.icon, style: const TextStyle(fontSize: 18)),
            const SizedBox(width: 8),
            Text(k == 'battery' ? tr('m.battery') : mt.label, style: const TextStyle(fontSize: 15)),
          ]),
          const SizedBox(height: 6),
          Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
            Text(value, style: const TextStyle(fontSize: 30, fontWeight: FontWeight.w800)),
            const SizedBox(width: 6),
            Padding(
                padding: const EdgeInsets.only(bottom: 5),
                child: Text(unit, style: const TextStyle(color: C.muted, fontSize: 15))),
            const Spacer(),
            if (trend.length >= 2) Sparkline(trend, color: V2.blue),
          ]),
          Row(children: [
            if (normal != null)
              Text(normal ? tr('v2.normal') : tr('v2.watch'),
                  style: TextStyle(color: normal ? V2.green : V2.orange, fontWeight: FontWeight.w600)),
            const Spacer(),
            Text(ago(ts), style: const TextStyle(color: C.muted, fontSize: 12)),
          ]),
        ]),
      ),
    );
  }
}
