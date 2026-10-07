import 'package:flutter/material.dart';

import '../i18n.dart';
import '../main.dart';
import '../model.dart';
import '../v2.dart';
import '../widgets.dart';
import 'resident.dart';

/// V2 · écran 1 « Mes résidents » : recherche, filtres Tous / Détectés / Non détectés, une carte par résident
/// (vert = détectée ≤ 15 s · orange = information ancienne ≤ 2 min · rouge = non détectée).
class ResidentsScreen extends StatefulWidget {
  const ResidentsScreen({super.key});
  @override
  State<ResidentsScreen> createState() => _ResidentsScreenState();
}

class _ResidentsScreenState extends State<ResidentsScreen> {
  String filter = 'all';
  String q = '';

  @override
  Widget build(BuildContext context) {
    final m = ModelScope.of(context);
    return Every(builder: (context) {
      final now = m.serverNow();
      final all = [for (final r in m.rings) (r, detectionOf(r, now))];
      final det = all.where((x) => x.$2.isDetected).length;
      final query = q.trim().toLowerCase();
      final shown = all.where((x) {
        if (filter == 'det' && !x.$2.isDetected) return false;
        if (filter == 'not' && x.$2.isDetected) return false;
        if (query.isEmpty) return true;
        final r = x.$1;
        return [r.resident, r.ringId, r.mac, x.$2.zone ?? ''].any((s) => s.toLowerCase().contains(query));
      }).toList();

      return RefreshIndicator(
        onRefresh: m.refreshRings,
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.fromLTRB(14, 12, 14, 20),
          children: [
            TabHeader(tr('v2.residents'), live: m.streaming),
            const SizedBox(height: 14),
            TextField(
              onChanged: (v) => setState(() => q = v),
              decoration: InputDecoration(
                hintText: tr('v2.search'),
                prefixIcon: const Icon(Icons.search, color: C.muted),
                filled: true,
                fillColor: V2.card,
                isDense: true,
                contentPadding: const EdgeInsets.symmetric(vertical: 12),
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(14), borderSide: BorderSide.none),
              ),
            ),
            const SizedBox(height: 12),
            SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: Row(children: [
                FilterChipV2(tr('v2.all', [all.length]), filter == 'all', () => setState(() => filter = 'all')),
                const SizedBox(width: 8),
                FilterChipV2(tr('v2.detected_f', [det]), filter == 'det', () => setState(() => filter = 'det')),
                const SizedBox(width: 8),
                FilterChipV2(tr('v2.not_detected_f', [all.length - det]), filter == 'not',
                    () => setState(() => filter = 'not')),
              ]),
            ),
            const SizedBox(height: 14),
            if (m.rings.isEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 60),
                child: Text(tr('rings.none'), textAlign: TextAlign.center, style: const TextStyle(color: C.muted)),
              ),
            for (final x in shown) ResidentCard(x.$1, x.$2),
          ],
        ),
      );
    });
  }
}

class ResidentCard extends StatelessWidget {
  final RingItem r;
  final Detection d;
  const ResidentCard(this.r, this.d, {super.key});

  @override
  Widget build(BuildContext context) {
    final line = cardLine(r, d);
    final zone = zoneLine(d);
    final border = d.det == Det.detected && !batteryLow(r)
        ? V2.green
        : d.det == Det.notDetected
            ? V2.red
            : d.det == Det.old || batteryLow(r)
                ? V2.orange
                : C.line;
    final running = r.runningMeasure;
    // Historique des dernières mesures constatées : la dernière valeur de chaque capteur autorisé,
    // de la plus récente à la plus ancienne (5 au plus)
    final hist = <(int, String)>[];
    for (final mt in metrics) {
      final v = r.values[mt.key];
      if (mt.key == 'battery' || v is! Map || !(r.visible.isEmpty || r.visible.contains(mt.key))) continue;
      final ts = ((v['ts'] as num?) ?? 0).toInt();
      hist.add((ts, '${mt.icon} ${tr('btn.${mt.key}')} ${formatValue(mt.key, v['data'] as Map?)}'
          '${mt.unit.isEmpty ? '' : ' ${mt.unit}'} · ${ago(ts)}'));
    }
    hist.sort((a, b) => b.$1.compareTo(a.$1));
    final lines = hist.take(5).map((x) => x.$2).toList();
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => ResidentScreen(mac: r.mac))),
        child: Container(
          padding: const EdgeInsets.fromLTRB(12, 12, 8, 12),
          decoration: BoxDecoration(
            color: border.withOpacity(.07),
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: border.withOpacity(.75), width: 1.4),
          ),
          child: Row(children: [
            ResidentAvatar(r, dim: d.det == Det.gwOff || d.det == Det.unbound),
            const SizedBox(width: 12),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [
                  Expanded(
                    child: Text(r.resident,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
                  ),
                  BatteryChip(r.battery, charging: r.charging),
                ]),
                Text(r.ringId, style: const TextStyle(color: C.muted, fontSize: 12.5)),
                const SizedBox(height: 3),
                Row(children: [
                  Icon(Icons.circle, size: 9, color: line.color),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Text(line.text,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(color: line.color, fontSize: 12.5, fontWeight: FontWeight.w600)),
                  ),
                ]),
                if (running != null)
                  Text(tr('v2.running_banner', [tr('btn.$running')]),
                      style: const TextStyle(color: V2.teal, fontSize: 12, fontWeight: FontWeight.w600)),
                if (zone != null)
                  Text(zone,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(color: C.text, fontSize: 13)),
                if (lines.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 6, bottom: 1),
                    child: Text(tr('rings.last_values'),
                        style: const TextStyle(color: C.muted, fontSize: 12, fontWeight: FontWeight.w600)),
                  ),
                for (final l in lines)
                  Text(l, maxLines: 1, overflow: TextOverflow.ellipsis,
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
