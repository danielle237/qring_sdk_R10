import 'package:flutter/material.dart';

import '../i18n.dart';
import '../main.dart';
import '../model.dart';
import '../v2.dart';
import '../widgets.dart';
import 'history.dart';
import 'measure.dart';
import 'ring.dart' show CheckPanel;
import 'sleep.dart';
import 'sleep_charts.dart';

/// Ordre des tuiles « Dernières mesures » (selon les droits du compte)
const kTileOrder = ['hr', 'spo2', 'temp', 'hrv', 'stress', 'fatigue', 'health', 'steps', 'bp'];

/// V2 · écran 2 « Détail d'un résident » : bague détectée (pièce, gateway, RSSI, dernière détection),
/// dernières mesures, « MESURER HR + SpO₂ » et « Autres mesures ».
class ResidentScreen extends StatelessWidget {
  final String mac;
  const ResidentScreen({super.key, required this.mac});

  @override
  Widget build(BuildContext context) {
    final m = ModelScope.of(context);
    final r = m.ringByMac(mac);
    if (r == null) {
      return Scaffold(appBar: AppBar(), body: Center(child: Text(tr('rings.none'), textAlign: TextAlign.center)));
    }
    return Scaffold(
      appBar: AppBar(
        centerTitle: true,
        title: Row(mainAxisSize: MainAxisSize.min, children: [
          ResidentAvatar(r, size: 40),
          const SizedBox(width: 10),
          Flexible(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(r.resident,
                  maxLines: 1, overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 18)),
              Text(r.ringId, style: const TextStyle(color: C.muted, fontSize: 13)),
            ]),
          ),
        ]),
        actions: [_Menu(r)],
      ),
      body: Every(builder: (context) {
        final now = m.serverNow();
        final d = detectionOf(r, now);
        final running = r.runningMeasure;
        // Mesure déjà en cours (autre compte) : bouton actif → le serveur répond « patientez » et prévient à la fin
        final canStart = r.online && r.canTry && r.ringState != 'unbound';
        final tiles = kTileOrder.where((k) => r.visible.contains(k)).toList();
        final canAll = r.measures.contains('hr') && r.measures.contains('spo2');
        return RefreshIndicator(
          onRefresh: m.refreshRings,
          child: ListView(
            padding: const EdgeInsets.fromLTRB(14, 6, 14, 24),
            children: [
              _StatusCard(r, d),
              CheckPanel(r),
              if (running != null) _RunningBanner(r, running),
              Padding(
                padding: const EdgeInsets.fromLTRB(2, 18, 2, 8),
                child: Row(children: [
                  Expanded(
                    child: Text(tr('v2.last_measures'),
                        style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
                  ),
                  if (r.canHistory)
                    TextButton(
                      onPressed: () =>
                          Navigator.of(context).push(MaterialPageRoute(builder: (_) => HistoryScreen(mac: r.mac))),
                      child: Text('${tr('v2.history')}  ›', style: const TextStyle(color: C.text)),
                    ),
                ]),
              ),
              GridView.count(
                crossAxisCount: 2,
                shrinkWrap: true,
                physics: const NeverScrollableScrollPhysics(),
                crossAxisSpacing: 8,
                mainAxisSpacing: 8,
                childAspectRatio: 1.45,
                children: [
                  for (final k in tiles)
                    _Tile(r, k, tileState(r, k, running, now),
                        canTap: canStart && r.measures.contains(k)),
                ],
              ),
              const SizedBox(height: 16),
              if (canAll && r.showAllBtn)
                FilledButton.icon(
                  onPressed: canStart ? () => openMeasure(context, r, 'all') : null,
                  icon: const Icon(Icons.play_arrow_rounded, size: 26),
                  // Gateway Linux : HR → SpO₂ → T° → HRV en une connexion (colmi_4_mesures_v3_clean.py)
                  label: FittedBox(
                    fit: BoxFit.scaleDown,
                    child: Text(tr(r.isLinux ? 'v2.measure_main' : 'v2.measure_main_tv'),
                        style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 16)),
                  ),
                  style: FilledButton.styleFrom(
                    backgroundColor: V2.teal,
                    foregroundColor: const Color(0xFF06201D),
                    disabledBackgroundColor: V2.teal.withOpacity(.25),
                    padding: const EdgeInsets.symmetric(vertical: 15),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(26)),
                  ),
                ),
              const SizedBox(height: 10),
              if (r.showOtherBtn)
              OutlinedButton(
                onPressed: () => showOtherMeasures(context, r),
                style: OutlinedButton.styleFrom(
                  padding: const EdgeInsets.symmetric(vertical: 14),
                  side: const BorderSide(color: C.line),
                  backgroundColor: V2.card,
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(26)),
                ),
                child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                  Text(tr('v2.other'), style: const TextStyle(color: C.text, fontWeight: FontWeight.w600)),
                  const SizedBox(width: 8),
                  const Icon(Icons.chevron_right, color: C.muted),
                ]),
              ),
              if (r.canHistory) ...[
                const SizedBox(height: 10),
                Row(children: [
                  Expanded(
                    child: _SmallButton('🛏', tr('v2.sleep_hist'),
                        () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => SleepScreen(mac: r.mac)))),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: _SmallButton('📊', tr('v2.sleep_charts'),
                        () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => SleepChartsScreen(mac: r.mac)))),
                  ),
                ]),
              ],
            ],
          ),
        );
      }),
    );
  }
}

/// Ouvre l'écran « Mesure en cours » (lance la mesure) ou suit la mesure déjà en cours ([follow]).
void openMeasure(BuildContext context, RingItem r, String cmd, {bool follow = false}) {
  Navigator.of(context).push(MaterialPageRoute(builder: (_) => MeasureScreen(mac: r.mac, cmd: cmd, follow: follow)));
}

class _StatusCard extends StatelessWidget {
  final RingItem r;
  final Detection d;
  const _StatusCard(this.r, this.d);

  @override
  Widget build(BuildContext context) {
    final color = d.color;
    final title = switch (d.det) {
      Det.detected => tr(r.isLinux ? 'v2.ring_detected' : 'v2.ring_associated'),
      Det.old => tr('v2.ring_old'),
      Det.notDetected => tr('v2.ring_not_detected'),
      Det.gwOff => tr('v2.gw_off'),
      Det.unbound => tr('v2.unbound'),
    };
    final loc = r.location;
    // Gateway Linux : Pi de la dernière détection (gardée quand la bague n'est plus entendue)
    final gw = r.isLinux ? ((loc?['seenGateway'] ?? loc?['gateway']) as String?) : ((r.live['deviceName'] as String?) ?? r.live['gateway'] as String?);
    // Signal : Pi → test de portée ; TV Android → lu par la TV sur la connexion (si activé dans l'admin)
    final rssi = d.isDetected ? (r.isLinux ? (loc?['rssi']) : (r.live['rssi'])) : null;
    final prevGw = r.isLinux ? (loc?['prevGateway'] as String?) : null;
    final prevTs = ((loc?['prevTs'] as num?) ?? 0).toInt();
    final zone = zoneLine(d);
    String when;
    if (d.det == Det.detected && d.ageSec == null) {
      when = tr('v2.connected_tv');
    } else if (d.ageSec != null) {
      when = '${agoV2(d.ageSec!)} · ${dayHm(nowSec() - d.ageSec!)}';     // « il y a 12 min · 14:32 »
    } else {
      when = '—';
    }
    Widget info(IconData ic, String a, [String? b, String? c]) => Padding(
          padding: const EdgeInsets.only(top: 10),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Icon(ic, size: 19, color: C.text),
            const SizedBox(width: 10),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(a, style: TextStyle(fontSize: b == null ? 14.5 : 13, color: b == null ? C.text : C.muted)),
                if (b != null) Text(b, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 14)),
                if (c != null) Text(c, style: const TextStyle(color: C.muted, fontSize: 12.5)),
              ]),
            ),
          ]),
        );
    return Container(
      padding: const EdgeInsets.fromLTRB(14, 14, 14, 14),
      decoration: BoxDecoration(
        color: color.withOpacity(.08),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: color.withOpacity(.8), width: 1.4),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Icon(Icons.circle, size: 14, color: color),
          const SizedBox(width: 8),
          Expanded(
            child: Text(title, style: TextStyle(color: color, fontSize: 17, fontWeight: FontWeight.w800)),
          ),
        ]),
        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              if (zone != null) info(Icons.place_outlined, zone),
              if (gw != null && gw.isNotEmpty)
                info(Icons.home_outlined, tr('v2.gw_current'), gw, rssi != null ? tr('v2.rssi', [rssi]) : null),
              info(Icons.schedule, r.isLinux ? tr('v2.heard') : tr('v2.last_detection'), when),
              // Pi précédente (où la bague était avant la Pi actuelle) + heure ; rien s'il n'y en a pas
              if (prevGw != null && prevGw.isNotEmpty)
                info(Icons.history, tr('v2.last_detection'), prevGw, prevTs > 0 ? dayHm(prevTs) : null),
            ]),
          ),
          Padding(padding: const EdgeInsets.only(top: 8), child: BatteryGauge(r)),
        ]),
      ]),
    );
  }
}

class _RunningBanner extends StatelessWidget {
  final RingItem r;
  final String running;
  const _RunningBanner(this.r, this.running);
  @override
  Widget build(BuildContext context) {
    final wait = (r.pending[running] as Map?)?['waitFor'] as Map?;
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Container(
        padding: const EdgeInsets.fromLTRB(12, 8, 6, 8),
        decoration: BoxDecoration(
            color: V2.teal.withOpacity(.1), borderRadius: BorderRadius.circular(14), border: Border.all(color: V2.teal)),
        child: Row(children: [
          const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2.4, color: V2.teal)),
          const SizedBox(width: 10),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(tr('v2.running_banner', [tr('btn.$running')]),
                  style: const TextStyle(color: V2.teal, fontWeight: FontWeight.w700)),
              if (wait?['message'] != null)
                Text('${wait!['message']}', style: const TextStyle(color: V2.orange, fontSize: 12)),
            ]),
          ),
          TextButton(onPressed: () => openMeasure(context, r, running, follow: true), child: Text(tr('v2.see'))),
        ]),
      ),
    );
  }
}

class _SmallButton extends StatelessWidget {
  final String icon;
  final String label;
  final VoidCallback onTap;
  const _SmallButton(this.icon, this.label, this.onTap);
  @override
  Widget build(BuildContext context) => OutlinedButton(
        onPressed: onTap,
        style: OutlinedButton.styleFrom(
          padding: const EdgeInsets.symmetric(vertical: 13, horizontal: 6),
          side: const BorderSide(color: C.line),
          backgroundColor: V2.card,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        ),
        child: FittedBox(
          fit: BoxFit.scaleDown,
          child: Text('$icon  $label', style: const TextStyle(color: C.text, fontWeight: FontWeight.w600)),
        ),
      );
}

/// État d'une box pendant / juste après une mesure :
///  active = mesure en cours (turquoise ⏳) · fresh = valeur arrivée (vert « ✓ à l'instant »)
///  queued = pas encore mesurée dans cette série (ancienne valeur, « en attente ») · normal
String tileState(RingItem r, String k, String? running, int now) {
  final ts = (((r.values[k] as Map?)?['ts']) as num?)?.toInt() ?? 0;
  // Mesure de cette case en cours (lancée ici, depuis un autre écran ou par un autre compte) : « en cours »
  if (running != 'all' && r.pending.containsKey(k)) return 'active';
  if (running == null) return ts > 0 && now - ts < 60 ? 'fresh' : 'normal';
  final seq = running == 'all'
      ? (r.isLinux ? const ['hr', 'spo2', 'temp', 'hrv'] : const ['hr', 'spo2'])
      : [running];
  if (!seq.contains(k)) return ts > 0 && now - ts < 60 ? 'fresh' : 'normal';
  final p = r.pending[running] as Map?;
  final start = ((p?['requested'] ?? p?['since']) as num?)?.toInt() ?? now;
  bool done(String x) => ((((r.values[x] as Map?)?['ts']) as num?)?.toInt() ?? 0) >= start - 1;
  if (done(k)) return 'fresh';
  final current = seq.firstWhere((x) => !done(x), orElse: () => k);
  return current == k ? 'active' : 'queued';
}

class _Tile extends StatelessWidget {
  final RingItem r;
  final String k;
  final String state;
  final bool canTap;
  const _Tile(this.r, this.k, this.state, {this.canTap = false});

  @override
  Widget build(BuildContext context) {
    final active = state == 'active';
    final fresh = state == 'fresh';
    final mt = metricOf(k);
    final v = r.values[k] as Map?;
    final data = v?['data'] as Map?;
    final ts = ((v?['ts'] as num?) ?? 0).toInt();
    final err = r.errors[k] as Map?;
    final errTs = ((err?['ts'] as num?) ?? 0).toInt();
    // Erreur plus récente que la valeur, et de moins d'1 h : sinon la case montre la dernière valeur
    final errNewer = err != null && errTs > ts && ModelScope.of(context).serverNow() - errTs < 3600;
    String sub;
    if (active) {
      sub = tr('v2.tile_measuring');
    } else if (fresh) {
      sub = '✓ ${ago(ts)}';
    } else if (state == 'queued') {
      sub = '${v == null ? tr('ring.no_value') : ago(ts)} · ${tr('v2.tile_queued')}';
    } else if (errNewer) {
      sub = tr('err.${err!['code']}');
    } else if (v == null) {
      sub = tr('ring.no_value');
    } else {
      sub = ago(ts);
    }
    final dist = data?['distance'] as num?;
    final unit = k == 'stress' ? '/ 100' : mt.unit;
    return Material(
      color: V2.card,
      borderRadius: BorderRadius.circular(16),
      child: InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: canTap && !active ? () => openMeasure(context, r, k) : null,
        child: Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(16),
            border: Border.all(
                color: active ? V2.teal : fresh ? V2.green : C.line.withOpacity(.6), width: active || fresh ? 1.6 : 1),
          ),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Text(mt.icon, style: const TextStyle(fontSize: 17)),
              const SizedBox(width: 7),
              Expanded(
                child: Text(mt.label, maxLines: 2, overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontSize: 12.5, height: 1.1)),
              ),
            ]),
            const Spacer(),
            Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
              if (active)
                const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2.5, color: V2.teal))
              else
                Text(formatValue(k, data), style: const TextStyle(fontSize: 25, fontWeight: FontWeight.w800)),
              const SizedBox(width: 5),
              if (!active && data != null && unit.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(bottom: 3),
                  child: Text(unit, style: const TextStyle(color: C.muted, fontSize: 13)),
                ),
            ]),
            if (k == 'steps' && dist != null && !active)
              Text(tr('ring.km', [(dist / 1000).toStringAsFixed(1).replaceAll('.', appLang == 'en' ? '.' : ','), kcal(data)]),
                  style: const TextStyle(color: C.muted, fontSize: 11.5)),
            Text(sub, maxLines: 1, overflow: TextOverflow.ellipsis,
                style: TextStyle(
                    color: active ? V2.teal : fresh ? V2.green : errNewer ? V2.red : C.muted,
                    fontSize: 11.5,
                    fontWeight: active || fresh ? FontWeight.w700 : FontWeight.w400)),
          ]),
        ),
      ),
    );
  }
}

/// Menu « … » : actualiser, alertes de ce résident, historique, sommeil
class _Menu extends StatelessWidget {
  final RingItem r;
  const _Menu(this.r);
  @override
  Widget build(BuildContext context) {
    final m = ModelScope.of(context);
    return PopupMenuButton<String>(
      icon: const Icon(Icons.more_horiz),
      color: V2.card2,
      onSelected: (v) {
        switch (v) {
          case 'refresh':
            m.startCheck(r);
          case 'alerts':
            m.setNotifyRing(r, !r.notify).catchError((Object e) {
              if (context.mounted) toast(context, '$e', color: C.err);
            });
          case 'history':
            Navigator.of(context).push(MaterialPageRoute(builder: (_) => HistoryScreen(mac: r.mac)));
          case 'sleep':
            Navigator.of(context).push(MaterialPageRoute(builder: (_) => SleepScreen(mac: r.mac)));
          case 'sleepg':
            Navigator.of(context).push(MaterialPageRoute(builder: (_) => SleepChartsScreen(mac: r.mac)));
        }
      },
      itemBuilder: (_) => [
        PopupMenuItem(
          value: 'refresh',
          enabled: r.online && r.canTry,
          child: ListTile(leading: const Icon(Icons.refresh), title: Text(tr('v2.refresh')), dense: true),
        ),
        if (r.canAlerts)
          PopupMenuItem(
            value: 'alerts',
            child: ListTile(
              leading: Icon(r.notify ? Icons.notifications_active : Icons.notifications_off,
                  color: r.notify ? V2.teal : C.muted),
              title: Text(tr('v2.alerts_ring')),
              trailing: Text(r.notify ? tr('v2.on') : tr('v2.off'), style: const TextStyle(color: C.muted, fontSize: 12)),
              dense: true,
            ),
          ),
        if (r.canHistory) ...[
          PopupMenuItem(
              value: 'history',
              child: ListTile(leading: const Icon(Icons.show_chart), title: Text(tr('v2.history')), dense: true)),
          PopupMenuItem(
              value: 'sleep',
              child: ListTile(leading: const Icon(Icons.bedtime_outlined), title: Text(tr('v2.sleep')), dense: true)),
          PopupMenuItem(
              value: 'sleepg',
              child: ListTile(leading: const Icon(Icons.insights), title: Text(tr('v2.sleep_charts')), dense: true)),
        ],
      ],
    );
  }
}

/// V2 · écran 8 « Mesures disponibles » (feuille du bas)
void showOtherMeasures(BuildContext context, RingItem r) {
  final m = ModelScope.read(context);
  showModalBottomSheet(
    context: context,
    backgroundColor: V2.card,
    showDragHandle: true,
    isScrollControlled: true,
    shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(22))),
    builder: (ctx) {
      final cur = m.ringByMac(r.mac) ?? r;
      final can = cur.online && cur.canTry && cur.ringState != 'unbound';
      void go(String k) {
        Navigator.pop(ctx);
        openMeasure(context, cur, k);
      }

      Widget big(String label, String icon, String k, {bool main = false}) => Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: SizedBox(
              width: double.infinity,
              child: FilledButton(
                onPressed: can ? () => go(k) : null,
                style: FilledButton.styleFrom(
                  backgroundColor: main ? V2.teal : V2.card2,
                  foregroundColor: main ? const Color(0xFF06201D) : C.text,
                  padding: const EdgeInsets.symmetric(vertical: 14),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                ),
                child: Text('$icon  $label', style: const TextStyle(fontWeight: FontWeight.w700)),
              ),
            ),
          );
      // « Autres mesures » : 4 boutons en haut, puis le reste
      // 4 boutons : fatigue · health-check · pressure (get-real-time …) · pas (get-steps)
      final rt = ['fatigue', 'health', 'stress', 'steps'].where((k) => cur.measures.contains(k)).toList();
      final others = ['temp', 'hrv', 'bp'].where((k) => cur.measures.contains(k)).toList();
      String lbl(String k) => k == 'battery' ? '🔋  ${tr('m.battery')}' : k == 'stress' ? '⚡  ${tr('v2.pressure')}' : '${metricOf(k).icon}  ${metricOf(k).label}';
      return SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(tr('v2.measure_title'), style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
            const SizedBox(height: 12),
            if (cur.measures.contains('hr') && cur.measures.contains('spo2'))
              big(cur.isLinux ? tr('v2.hr_spo2_reco') : tr('v2.measure_main_tv'), '❤️', 'all', main: true),
            if (rt.isNotEmpty) ...[
              Row(children: [
                for (final k in rt)
                  Expanded(
                    child: Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 3),
                      child: FilledButton(
                        onPressed: can ? () => go(k) : null,
                        style: FilledButton.styleFrom(
                          backgroundColor: V2.card2,
                          foregroundColor: C.text,
                          padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 4),
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                        ),
                        child: Column(mainAxisSize: MainAxisSize.min, children: [
                          Text(k == 'stress' ? '⚡' : metricOf(k).icon, style: const TextStyle(fontSize: 20)),
                          const SizedBox(height: 4),
                          FittedBox(
                            fit: BoxFit.scaleDown,
                            child: Text(k == 'stress' ? tr('v2.pressure') : metricOf(k).label,
                                style: const TextStyle(fontWeight: FontWeight.w700)),
                          ),
                        ]),
                      ),
                    ),
                  ),
              ]),
              const SizedBox(height: 10),
            ],
            if (cur.measures.contains('hr')) big(tr('v2.hr_only'), '❤️', 'hr'),
            if (cur.measures.contains('spo2')) big(tr('v2.spo2_only'), '💧', 'spo2'),
            const SizedBox(height: 6),
            Wrap(spacing: 8, runSpacing: 8, children: [
              for (final k in [...others, 'battery'])
                SizedBox(
                  width: (MediaQuery.of(ctx).size.width - 32 - 8) / 2,
                  child: OutlinedButton(
                    onPressed: can ? () => go(k) : null,
                    style: OutlinedButton.styleFrom(
                      padding: const EdgeInsets.symmetric(vertical: 13),
                      side: const BorderSide(color: C.line),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                    ),
                    child: Text(lbl(k), style: const TextStyle(color: C.text, fontWeight: FontWeight.w600)),
                  ),
                ),
            ]),
          ]),
        ),
      );
    },
  );
}
