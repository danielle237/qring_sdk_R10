import 'package:flutter/material.dart';

import '../i18n.dart';
import '../main.dart';
import '../widgets.dart';
import 'ring.dart';

/// Dernières alertes des bagues du compte (retirée, hors portée, dissociée, Gateway RHM hors ligne, batterie, rétablie).
class AlertsScreen extends StatelessWidget {
  const AlertsScreen({super.key});

  Color _color(String? kind) => switch (kind) {
        'removed' || 'battery_low' || 'unbound' => C.warn,
        'out_of_range' || 'gateway_offline' => C.err,
        _ => C.ok,
      };

  @override
  Widget build(BuildContext context) {
    final m = ModelScope.of(context);
    return RefreshIndicator(
      onRefresh: m.loadAlerts,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(14, 10, 14, 20),
        children: [
          Text(tr('tab.alerts'), style: const TextStyle(fontSize: 21, fontWeight: FontWeight.w800)),
          const SizedBox(height: 12),
          if (m.alerts.isEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 60),
              child: Text(tr('al.none'), textAlign: TextAlign.center, style: const TextStyle(color: C.muted)),
            ),
          for (final a in m.alerts)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: InkWell(
                borderRadius: BorderRadius.circular(16),
                onTap: () {
                  final r = m.ringByMac('${a['mac']}'.toUpperCase());
                  if (r != null) {
                    Navigator.of(context).push(MaterialPageRoute(builder: (_) => RingScreen(mac: r.mac)));
                  }
                },
                child: Panel(
                  border: _color(a['kind'] as String?),
                  child: Row(children: [
                    Expanded(
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Text('${a['title'] ?? ''}',
                            style: TextStyle(color: _color(a['kind'] as String?), fontWeight: FontWeight.w700)),
                        const SizedBox(height: 3),
                        Text('💍 ${a['label'] ?? a['mac']}', style: const TextStyle(fontWeight: FontWeight.w600)),
                        Text('${a['message'] ?? ''}', style: const TextStyle(color: C.muted, fontSize: 12)),
                      ]),
                    ),
                    Text(dayHm(((a['ts'] as num?) ?? 0).toInt()), style: const TextStyle(color: C.muted, fontSize: 12)),
                  ]),
                ),
              ),
            ),
        ],
      ),
    );
  }
}
