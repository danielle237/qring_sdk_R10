import 'package:flutter/material.dart';

import '../i18n.dart';
import '../main.dart';
import '../model.dart';
import '../widgets.dart';
import 'ring.dart';

/// « Mes bagues » : état de chaque bague en temps réel (Mosquitto → serveur → flux de l'app).
class RingsScreen extends StatelessWidget {
  const RingsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final m = ModelScope.of(context);
    final alertable = m.rings.where((r) => r.canAlerts).toList();
    final allOn = alertable.isNotEmpty && alertable.every((r) => r.notify);
    final globalOff = m.user?['alertsEnabled'] == false;

    return RefreshIndicator(
      onRefresh: m.refreshRings,
      // Bagues en haut, logo « EHPAD de la Vie » toujours tout en bas, centré
      child: CustomScrollView(
        physics: const AlwaysScrollableScrollPhysics(),
        slivers: [
          SliverPadding(
            padding: const EdgeInsets.fromLTRB(14, 10, 14, 0),
            sliver: SliverList(
              delegate: SliverChildListDelegate([
          Row(children: [
            ClipRRect(borderRadius: BorderRadius.circular(8), child: Image.asset('assets/icon.png', width: 32, height: 32)),
            const SizedBox(width: 10),
            Expanded(child: Text(tr('rings.title'), style: const TextStyle(fontSize: 21, fontWeight: FontWeight.w800))),
            Icon(Icons.circle, size: 9, color: m.streaming ? C.ok : C.warn),
            const SizedBox(width: 5),
            Text(m.streaming ? tr('live.on') : tr('live.off'), style: const TextStyle(color: C.muted, fontSize: 12)),
          ]),
          const SizedBox(height: 12),
          if (alertable.isNotEmpty)
            Panel(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
              child: Row(children: [
                const Icon(Icons.notifications_active_outlined, color: C.muted, size: 20),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(tr('rings.alerts_all'), style: const TextStyle(fontWeight: FontWeight.w600)),
                    if (globalOff)
                      Text(tr('rings.alerts_off_global'), style: const TextStyle(color: C.warn, fontSize: 11)),
                  ]),
                ),
                Switch(value: allOn, onChanged: (v) => m.setNotifyAll(v).catchError((Object e) {
                  if (context.mounted) toast(context, '$e', color: C.err);
                })),
              ]),
            ),
          const SizedBox(height: 10),
          if (m.rings.isEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 60),
              child: Text(tr('rings.none'), textAlign: TextAlign.center, style: const TextStyle(color: C.muted)),
            ),
          for (final r in m.rings) _RingCard(r),
              ]),
            ),
          ),
          SliverFillRemaining(
            hasScrollBody: false,
            child: Align(
              alignment: Alignment.bottomCenter,
              child: Padding(
                padding: const EdgeInsets.only(top: 24, bottom: 16),
                child: Column(mainAxisSize: MainAxisSize.min, children: [
                  ClipRRect(
                    borderRadius: BorderRadius.circular(28),
                    child: Image.asset('assets/logo_epat.png', width: 170, height: 170),
                  ),
                  const SizedBox(height: 10),
                  Text(tr('app.org'), textAlign: TextAlign.center,
                      style: const TextStyle(color: C.text, fontSize: 18, fontWeight: FontWeight.w500)),
                ]),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _RingCard extends StatelessWidget {
  final RingItem r;
  const _RingCard(this.r);

  @override
  Widget build(BuildContext context) {
    final s = ringStatus(r);
    // Dernière valeur de chaque capteur : icône · nom · valeur · il y a
    final lines = <String>[
      for (final mt in metrics)
        if (r.values[mt.key] is Map)
          '${mt.icon} ${tr('btn.${mt.key}')} ${formatValue(mt.key, (r.values[mt.key] as Map)['data'] as Map?)}'
              '${mt.unit.isEmpty ? '' : ' ${mt.unit}'} · ${ago((((r.values[mt.key] as Map)['ts'] as num?) ?? 0).toInt())}',
    ];
    final tv = (r.live['deviceName'] as String?)?.isNotEmpty == true ? r.live['deviceName'] : r.live['gateway'];

    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => RingScreen(mac: r.mac))),
        child: Panel(
          border: s.color,
          child: Row(children: [
            Column(mainAxisSize: MainAxisSize.min, children: [
              BatteryRing(r.battery, size: 50),
              if (r.battery != null && r.batteryTs > 0)
                Padding(
                  padding: const EdgeInsets.only(top: 3),
                  child: Text(ago(r.batteryTs), style: const TextStyle(color: C.muted, fontSize: 10)),
                ),
            ]),
            const SizedBox(width: 12),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [
                  Expanded(
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text('💍 ${r.title}',
                          maxLines: 1, overflow: TextOverflow.ellipsis,
                          style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
                      // Nom donné dans l'admin (base de données)
                      if (r.subName != null)
                        Padding(
                          padding: const EdgeInsets.only(left: 24),
                          child: Text('(${r.subName})',
                              maxLines: 1, overflow: TextOverflow.ellipsis,
                              style: const TextStyle(color: C.text, fontSize: 13, fontWeight: FontWeight.w500)),
                        ),
                    ]),
                  ),
                  if (r.canAlerts)
                    Icon(r.notify ? Icons.notifications_active : Icons.notifications_off, size: 17,
                        color: r.notify ? C.accent : C.muted),
                ]),
                // « Dernier état constaté : » + bouton ⟳ sur la même ligne
                Row(children: [
                  Expanded(
                    child: Text(tr('rings.last_state'),
                        style: const TextStyle(color: C.muted, fontSize: 12, fontWeight: FontWeight.w600)),
                  ),
                  _CardRefresh(r),
                ]),
                StatusPill(s),
                if (s.detail != null)
                  Padding(padding: const EdgeInsets.only(top: 3),
                      child: Text(s.detail!, style: TextStyle(color: s.color == C.err || s.color == C.warn ? s.color : C.muted, fontSize: 12))),
                LinkPills(r),
                LocationLine(r, size: 10.5),
                if (lines.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 8, bottom: 2),
                    child: Text(tr('rings.last_values'),
                        style: const TextStyle(color: C.muted, fontSize: 12, fontWeight: FontWeight.w600)),
                  ),
                for (final l in lines)
                  Text(l, maxLines: 1, overflow: TextOverflow.ellipsis,
                      style: const TextStyle(color: C.muted, fontSize: 12)),
                if (tv != null && '$tv'.isNotEmpty)
                  Text('📡 $tv', maxLines: 1, overflow: TextOverflow.ellipsis,
                      style: const TextStyle(color: C.muted, fontSize: 12)),
              ]),
            ),
            const Icon(Icons.chevron_right, color: C.muted),
          ]),
        ),
      ),
    );
  }
}

/// Bouton ⟳ sur la carte : « Actualiser l'état de la bague » sans ouvrir la page.
class _CardRefresh extends StatelessWidget {
  final RingItem r;
  const _CardRefresh(this.r);
  @override
  Widget build(BuildContext context) {
    final m = ModelScope.of(context);
    final st = m.checks[r.mac];
    final busy = st != null && st.running;
    final can = !busy && r.online && r.canTry;
    return IconButton(
      tooltip: tr('st.refresh'),
      visualDensity: VisualDensity.compact,
      padding: EdgeInsets.zero,
      constraints: const BoxConstraints(minWidth: 32, minHeight: 32),
      onPressed: can ? () => m.startCheck(r) : null,
      icon: busy
          ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
          : Icon(Icons.refresh, color: can ? C.accent : C.muted),
    );
  }
}
