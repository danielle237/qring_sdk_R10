import 'package:flutter/material.dart';

import '../api.dart';
import '../i18n.dart';
import '../main.dart';
import '../model.dart';
import '../widgets.dart';
import 'history.dart';
import 'sleep.dart';
import 'sleep_charts.dart';

/// Une bague : bandeau d'état, dernières mesures, boutons de mesure (selon les droits), « Actualiser l'état ».
class RingScreen extends StatelessWidget {
  final String mac;
  const RingScreen({super.key, required this.mac});

  @override
  Widget build(BuildContext context) {
    final m = ModelScope.of(context);
    final r = m.ringByMac(mac);
    if (r == null) {
      return Scaffold(appBar: AppBar(), body: Center(child: Text(tr('rings.none'), textAlign: TextAlign.center)));
    }
    final s = ringStatus(r);
    final tv = (r.live['deviceName'] as String?)?.isNotEmpty == true ? r.live['deviceName'] : r.live['gateway'];
    final running = r.runningMeasure;
    final visible = r.visible.where((k) => metrics.any((x) => x.key == k)).toList();

    return Scaffold(
      appBar: AppBar(title: Text(r.title, style: const TextStyle(fontWeight: FontWeight.w700))),
      body: RefreshIndicator(
        onRefresh: m.refreshRings,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(14, 4, 14, 24),
          children: [
            _AutoCheck(mac),
            // ---------------------------------------------------- bandeau d'infos
            Panel(
              color: C.card2,
              border: s.color,
              child: Row(children: [
                Column(mainAxisSize: MainAxisSize.min, children: [
                  BatteryRing(r.battery, size: 58),
                  if (r.battery != null && r.batteryTs > 0)
                    Padding(
                      padding: const EdgeInsets.only(top: 4),
                      child: Text(ago(r.batteryTs), style: const TextStyle(color: C.muted, fontSize: 10.5)),
                    ),
                  // Origine de la dernière lecture de batterie (📱 prise / actualisée)
                  if (r.values['battery'] is Map &&
                      sourceLabel((r.values['battery'] as Map)['source'] as String?).isNotEmpty)
                    SizedBox(
                      width: 70,
                      child: Text(
                        sourceLabel((r.values['battery'] as Map)['source'] as String?,
                            (r.values['battery'] as Map)['by'] as String?, (r.values['battery'] as Map)['via'] as String?),
                        textAlign: TextAlign.center,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(color: C.muted, fontSize: 9.5),
                      ),
                    ),
                ]),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    // Une seule ligne : le texte se réduit un peu s'il est trop long
                    FittedBox(
                      fit: BoxFit.scaleDown,
                      alignment: AlignmentDirectional.centerStart,
                      child: Text.rich(
                        TextSpan(children: [
                          TextSpan(text: r.realName.isNotEmpty ? r.realName : r.mac,
                              style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
                          // Nom donné dans l'admin (base de données), ex. « (Mme Martin) »
                          if (r.subName != null)
                            TextSpan(text: '  (${r.subName})',
                                style: const TextStyle(fontWeight: FontWeight.w500, fontSize: 13)),
                        ]),
                        maxLines: 1,
                        softWrap: false,
                      ),
                    ),
                    Text([r.mac, if (r.model.isNotEmpty) r.model].join(' · '),
                        style: const TextStyle(color: C.muted, fontSize: 12)),
                    if (tv != null && '$tv'.isNotEmpty)
                      Text(tr('rs.tv', [tv]), style: const TextStyle(color: C.muted, fontSize: 12)),
                    const SizedBox(height: 6),
                    StatusPill(s, size: 13),
                    if (s.detail != null)
                      Padding(
                        padding: const EdgeInsets.only(top: 3),
                        child: Text(s.detail!,
                            style: TextStyle(color: s.color == C.err || s.color == C.warn ? s.color : C.muted, fontSize: 12)),
                      ),
                    LinkPills(r, size: 11.5),
                    LocationLine(r),
                  ]),
                ),
                // Actualiser l'état de la bague (batterie + test de port)
                Align(
                  alignment: Alignment.topCenter,
                  child: _HeaderRefresh(r),
                ),
              ]),
            ),
            if (r.canAlerts)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Panel(
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 2),
                  child: Row(children: [
                    Icon(r.notify ? Icons.notifications_active : Icons.notifications_off,
                        color: r.notify ? C.accent : C.muted, size: 20),
                    const SizedBox(width: 10),
                    Expanded(child: Text(tr('ring.alerts'))),
                    Switch(value: r.notify, onChanged: (v) => m.setNotifyRing(r, v).catchError((Object e) {
                      if (context.mounted) toast(context, '$e', color: C.err);
                    })),
                  ]),
                ),
              ),
            CheckPanel(r),
            // ---------------------------------------------------- dernières mesures
            Padding(
              padding: const EdgeInsets.fromLTRB(4, 16, 4, 8),
              child: Text(tr('ring.last'), style: const TextStyle(color: C.muted, fontWeight: FontWeight.w600)),
            ),
            GridView.count(
              crossAxisCount: 2,
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              crossAxisSpacing: 8,
              mainAxisSpacing: 8,
              childAspectRatio: 1.55,
              children: [
                for (final k in visible)
                  _ValueCard(r, k, running == k || (running == 'all' && k != 'steps'),
                      canTap: r.measures.contains(k) && r.online && r.canTry &&
                          (running == null || running == k || k == 'steps')),
              ],
            ),
            // ---------------------------------------------------- boutons de mesure
            if (r.measures.isNotEmpty) ...[
              Padding(
                padding: const EdgeInsets.fromLTRB(4, 16, 4, 8),
                child: Text(tr('ring.launch'), style: const TextStyle(color: C.muted, fontWeight: FontWeight.w600)),
              ),
              Wrap(spacing: 8, runSpacing: 8, children: [
                for (final k in r.measures.where((k) => metrics.any((x) => x.key == k)))
                  _MeasureButton(r, k, enabled: r.online && r.canTry &&
                      (running == null || running == k || k == 'steps')),
                _MeasureButton(r, 'battery', enabled: r.online && r.canTry),
              ]),
            ],
            if (r.measures.isEmpty) ...[
              const SizedBox(height: 16),
              _MeasureButton(r, 'battery', enabled: r.online && r.canTry),
            ],
            const SizedBox(height: 14),
            _RefreshButton(r),
            if (r.canHistory) ...[
              const SizedBox(height: 10),
              OutlinedButton.icon(
                onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => HistoryScreen(mac: r.mac))),
                icon: const Icon(Icons.show_chart),
                label: Text(tr('ring.history')),
                style: OutlinedButton.styleFrom(
                    padding: const EdgeInsets.symmetric(vertical: 13),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14))),
              ),
              const SizedBox(height: 10),
              OutlinedButton.icon(
                onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => SleepScreen(mac: r.mac))),
                icon: const Icon(Icons.bedtime_outlined),
                label: Text(tr('sl.button')),
                style: OutlinedButton.styleFrom(
                    padding: const EdgeInsets.symmetric(vertical: 13),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14))),
              ),
              const SizedBox(height: 10),
              // 2ᵉ bouton : graphiques du sommeil (jour, semaine, mois, année) comme l'app QRing
              OutlinedButton.icon(
                onPressed: () =>
                    Navigator.of(context).push(MaterialPageRoute(builder: (_) => SleepChartsScreen(mac: r.mac))),
                icon: const Icon(Icons.insights),
                label: Text(tr('slg.button')),
                style: OutlinedButton.styleFrom(
                    padding: const EdgeInsets.symmetric(vertical: 13),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14))),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

/// Vérification automatique à l'ouverture de la page (comme la GATEWAY RHM à l'ouverture).
class _AutoCheck extends StatefulWidget {
  final String mac;
  const _AutoCheck(this.mac);
  @override
  State<_AutoCheck> createState() => _AutoCheckState();
}

class _AutoCheckState extends State<_AutoCheck> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      final m = ModelScope.read(context);
      final r = m.ringByMac(widget.mac);
      if (r != null) m.autoCheck(r);
    });
  }

  @override
  Widget build(BuildContext context) => const SizedBox.shrink();
}

/// Bouton ⟳ en haut à droite du bandeau.
class _HeaderRefresh extends StatelessWidget {
  final RingItem r;
  const _HeaderRefresh(this.r);
  @override
  Widget build(BuildContext context) {
    final m = ModelScope.of(context);
    final st = m.checks[r.mac];
    final busy = st != null && st.running;
    final can = !busy && r.online && r.canTry;
    return IconButton.filledTonal(
      tooltip: tr('st.refresh'),
      onPressed: can ? () => m.startCheck(r) : null,
      icon: busy
          ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
          : const Icon(Icons.refresh),
    );
  }
}

/// Lance une mesure (case ou bouton) et affiche la réponse.
Future<void> launchMeasure(BuildContext context, RingItem r, String k) async {
  try {
    final msg = await ModelScope.read(context).measure(r, k);
    if (context.mounted) toast(context, msg);
  } on ApiException catch (e) {
    if (context.mounted) toast(context, e.message, color: C.err);
  }
}

class _ValueCard extends StatelessWidget {
  final RingItem r;
  final String k;
  final bool active;
  final bool canTap;
  const _ValueCard(this.r, this.k, this.active, {this.canTap = false});

  @override
  Widget build(BuildContext context) {
    final mt = metricOf(k);
    final v = r.values[k] as Map?;
    final err = r.errors[k] as Map?;
    final errNewer = err != null && (((err['ts'] as num?) ?? 0) >= (((v?['ts']) as num?) ?? 0));
    final data = v?['data'] as Map?;
    String sub;
    if (active) {
      final since = ((r.pending[k] ?? r.pending['all']) as Map?)?['since'] as num?;
      sub = tr('rs.measuring', [tr('btn.$k'), since == null ? 0 : (nowSec() - since.toInt()).clamp(0, 999)]);
    } else if (errNewer) {
      sub = tr('ring.error', [tr('err.${err!['code']}'), ago(((err['ts'] as num?) ?? 0).toInt())]);
    } else if (v != null) {
      final ts = ((v['ts'] as num?) ?? 0).toInt();
      final src = sourceLabel(v['source'] as String?, v['by'] as String?, v['via'] as String?);
      sub = [ago(ts), if (src.isNotEmpty) src].join(' · ');
      final dist = data?['distance'] as num?;
      if (k == 'steps' && dist != null) {
        final km = (dist / 1000).toStringAsFixed(1);
        sub = [tr('ring.km', [km, kcal(data)]), ago(ts), if (src.isNotEmpty) src].join(' · ');
      }
    } else {
      sub = tr('ring.no_value');
    }
    final card = Panel(
      border: active ? mt.color : null,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Text(mt.icon),
          const SizedBox(width: 6),
          Expanded(child: Text(mt.label, maxLines: 1, overflow: TextOverflow.ellipsis,
              style: const TextStyle(color: C.muted, fontSize: 12))),
        ]),
        const Spacer(),
        Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
          if (active)
            SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2.5, color: mt.color))
          else
            Text(formatValue(k, data), style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w700)),
          const SizedBox(width: 4),
          if (!active && data != null) Text(mt.unit, style: const TextStyle(color: C.muted, fontSize: 12)),
        ]),
        const Spacer(),
        Text(sub, maxLines: 2, overflow: TextOverflow.ellipsis,
            style: TextStyle(color: errNewer && !active ? C.err : C.muted, fontSize: 11)),
      ]),
    );
    // Case cliquable : lance la mesure (comme sur la GATEWAY RHM)
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: canTap && !active ? () => launchMeasure(context, r, k) : null,
        child: card,
      ),
    );
  }
}

class _MeasureButton extends StatefulWidget {
  final RingItem r;
  final String k;
  final bool enabled;
  const _MeasureButton(this.r, this.k, {required this.enabled});
  @override
  State<_MeasureButton> createState() => _MeasureButtonState();
}

class _MeasureButtonState extends State<_MeasureButton> {
  bool sending = false;

  Future<void> _tap() async {
    setState(() => sending = true);
    try {
      final msg = await ModelScope.read(context).measure(widget.r, widget.k);
      if (mounted) toast(context, msg);
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, color: C.err);
    } finally {
      if (mounted) setState(() => sending = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final bat = widget.k == 'battery';
    final mt = metricOf(widget.k);
    final w = (MediaQuery.of(context).size.width - 28 - 16) / 3;
    return SizedBox(
      width: w,
      child: FilledButton(
        onPressed: widget.enabled && !sending ? _tap : null,
        style: FilledButton.styleFrom(
          backgroundColor: (bat ? C.ok : mt.color).withOpacity(.22),
          foregroundColor: C.text,
          padding: const EdgeInsets.symmetric(vertical: 13),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
        ),
        child: Text('${bat ? '🔋' : mt.icon} ${tr('btn.${widget.k}')}', maxLines: 1, overflow: TextOverflow.ellipsis),
      ),
    );
  }
}

class _RefreshButton extends StatelessWidget {
  final RingItem r;
  const _RefreshButton(this.r);
  @override
  Widget build(BuildContext context) {
    final m = ModelScope.of(context);
    final st = m.checks[r.mac];
    final busy = st != null && st.running;
    return FilledButton.icon(
      onPressed: busy || r.ringState == 'unbound' ? null : () => m.startCheck(r),
      icon: Icon(busy ? Icons.hourglass_top : Icons.refresh),
      label: Text(busy && st!.phase == CheckPhase.waiting ? tr('st.waiting') : tr('st.refresh'),
          style: const TextStyle(fontWeight: FontWeight.w700)),
      style: FilledButton.styleFrom(
        backgroundColor: const Color(0xFF2E9E6A),
        foregroundColor: Colors.white,
        padding: const EdgeInsets.symmetric(vertical: 15),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
      ),
    );
  }
}

/// Dernière mesure terminée : valeurs (plusieurs si « Tout mesurer ») ou bague retirée.
class _Finished {
  final String key;
  final int ts;
  final String text;
  final bool removed;
  final bool fromCheck; // valeur issue d'« Actualiser l'état » (reqId « …-r… »)
  _Finished(this.key, this.ts, this.text, this.removed, [this.fromCheck = false]);
}

const _measureKeys = ['hr', 'spo2', 'temp', 'bp', 'hrv', 'stress'];

_Finished? _lastFinished(RingItem r) {
  int best = 0;
  String? bestKey;
  for (final k in _measureKeys) {
    final ts = (((r.values[k] as Map?)?['ts']) as num?)?.toInt() ?? 0;
    if (ts > best) {
      best = ts;
      bestKey = k;
    }
  }
  // Erreur « bague retirée » plus récente que la dernière valeur
  for (final k in _measureKeys) {
    final e = r.errors[k] as Map?;
    final ts = (e?['ts'] as num?)?.toInt() ?? 0;
    if (e?['code'] == 'ring_removed' && ts > best) return _Finished(k, ts, '', true);
  }
  if (bestKey == null) return null;
  // Toutes les valeurs de la même mesure (« Tout mesurer » : même heure)
  final parts = [
    for (final k in _measureKeys)
      if (((((r.values[k] as Map?)?['ts']) as num?)?.toInt() ?? 0) >= best - 2)
        measureText(k, (r.values[k] as Map)['data'] as Map?),
  ];
  return _Finished(bestKey, best, parts.join(' · '), false, (r.values[bestKey] as Map)['via'] == 'r');
}

/// Résultat de « Actualiser l'état » (même règle que la TV et le bot).
class CheckPanel extends StatelessWidget {
  final RingItem r;
  const CheckPanel(this.r);
  @override
  Widget build(BuildContext context) {
    final m = ModelScope.of(context);
    final st = m.checks[r.mac];
    final now = m.serverNow();
    // Dernière mesure terminée (bouton, case, TV, serveur…) : le bandeau se met à jour pareil
    final fin = _lastFinished(r);
    final checkAt = st == null ? 0 : (st.wornAt ?? st.started);
    if (fin != null && now - fin.ts <= 120 &&
        (st == null || (!st.running && !fin.fromCheck && fin.ts > checkAt + 2))) {
      final color = fin.removed ? C.warn : C.ok;
      final text = fin.removed
          ? tr('st.measured_removed', [tr('btn.${fin.key}'), hm(fin.ts)])
          : '${tr('st.measured', [hm(fin.ts)])} · ${fin.text}';
      return Padding(
        padding: const EdgeInsets.only(top: 8),
        child: Panel(
          color: color.withOpacity(.13),
          border: color,
          child: Text(text, style: TextStyle(color: color, fontWeight: FontWeight.w700)),
        ),
      );
    }
    if (st == null) return const SizedBox.shrink();
    final elapsed = st.measureStart == null ? 0 : (now - st.measureStart!).clamp(0, 999);
    Color color;
    String text;
    double? progress;
    switch (st.phase) {
      case CheckPhase.requested:
        color = C.accent;
        text = tr('st.requested');
        break;
      case CheckPhase.checking:
        color = C.accent;
        text = tr('st.checking', [elapsed, m.wearCheck]);
        progress = elapsed / m.wearCheck;
        break;
      case CheckPhase.wornMeasuring:
        color = C.ok;
        text = '${tr('st.worn', [hm(st.wornAt!)])}\n${tr('rs.measuring', [tr('btn.hr'), elapsed])}';
        progress = elapsed / 60;
        break;
      case CheckPhase.worn:
        color = C.ok;
        text = tr('st.worn', [hm(st.wornAt ?? now)]) + (st.value != null ? ' · ${st.value}' : '');
        break;
      case CheckPhase.reachable:
        color = C.ok;
        text = tr('st.reachable', [hm(st.wornAt ?? now)]) + (st.value != null ? ' · ${st.value}' : '');
        break;
      case CheckPhase.removed:
        color = C.warn;
        text = tr('st.removed');
        break;
      case CheckPhase.out:
        color = C.err;
        text = tr('rs.out');
        break;
      case CheckPhase.gwOff:
        color = C.off;
        text = tr('rs.gw_off');
        break;
      case CheckPhase.waiting:
        color = C.accent;
        text = tr('st.waiting');
        break;
      case CheckPhase.unconfirmed:
        color = C.warn;
        text = st.message ?? tr('st.unconfirmed');
        break;
      case CheckPhase.failed:
        color = C.err;
        text = st.message ?? tr('st.unconfirmed');
        break;
    }
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Panel(
        color: color.withOpacity(.13),
        border: color,
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Text(text, style: TextStyle(color: color, fontWeight: FontWeight.w700)),
          if (st.running && progress != null) ...[
            const SizedBox(height: 8),
            LinearProgressIndicator(value: progress.clamp(0.0, 1.0), color: color, backgroundColor: C.line),
          ] else if (st.running) ...[
            const SizedBox(height: 8),
            LinearProgressIndicator(color: color, backgroundColor: C.line),
          ],
        ]),
      ),
    );
  }
}
