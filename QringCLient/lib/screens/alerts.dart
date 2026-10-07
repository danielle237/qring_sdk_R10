import 'package:flutter/material.dart';

import '../i18n.dart';
import '../main.dart';
import '../model.dart';
import '../v2.dart';
import '../widgets.dart';
import 'resident.dart';

const _gatewayKinds = {'gateway_offline', 'restored_gateway'};

/// V2 · écran 5 « Alertes » : filtres Toutes / Résidents / Gateways ; une carte par alerte
/// (bague non détectée, batterie faible, gateway hors ligne, mesure échouée, bague retirée…).
class AlertsScreen extends StatefulWidget {
  const AlertsScreen({super.key});
  @override
  State<AlertsScreen> createState() => _AlertsScreenState();
}

class _AlertsScreenState extends State<AlertsScreen> {
  String filter = 'all';

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) ModelScope.read(context).markAlertsSeen();
    });
  }

  static (IconData, Color) _look(String? kind) => switch (kind) {
        'out_of_range' => (Icons.radio_button_unchecked, V2.red),
        'gateway_offline' => (Icons.remove_circle, V2.red),
        'battery_low' => (Icons.battery_alert, V2.orange),
        'removed' || 'measure_failed' || 'unbound' => (Icons.info, V2.blue),
        _ => (Icons.check_circle, V2.green),
      };

  @override
  Widget build(BuildContext context) {
    final m = ModelScope.of(context);
    final gw = m.alerts.where((a) => _gatewayKinds.contains(a['kind'])).length;
    final res = m.alerts.length - gw;
    final shown = m.alerts.where((a) {
      final isGw = _gatewayKinds.contains(a['kind']);
      return filter == 'all' || (filter == 'gw' ? isGw : !isGw);
    }).toList();
    return RefreshIndicator(
      onRefresh: () async {
        await m.loadAlerts();
        m.markAlertsSeen();
      },
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(14, 12, 14, 20),
        children: [
          TabHeader(tr('tab.alerts'), live: m.streaming),
          const SizedBox(height: 14),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(children: [
              FilterChipV2(tr('v2.al_all', [m.alerts.length]), filter == 'all', () => setState(() => filter = 'all')),
              const SizedBox(width: 8),
              FilterChipV2(tr('v2.al_res', [res]), filter == 'res', () => setState(() => filter = 'res')),
              const SizedBox(width: 8),
              FilterChipV2(tr('v2.al_gw', [gw]), filter == 'gw', () => setState(() => filter = 'gw')),
            ]),
          ),
          const SizedBox(height: 14),
          if (shown.isEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 60),
              child: Text(tr('al.none'), textAlign: TextAlign.center, style: const TextStyle(color: C.muted)),
            ),
          for (final a in shown) _card(context, m, a),
        ],
      ),
    );
  }

  Widget _card(BuildContext context, AppModel m, Map<String, dynamic> a) {
    final kind = a['kind'] as String?;
    final (icon, color) = _look(kind);
    final r = m.ringByMac('${a['mac']}'.toUpperCase());
    final title = tr('v2.al.$kind') == 'v2.al.$kind' ? '${a['title'] ?? ''}' : tr('v2.al.$kind');
    final who = r == null ? '${a['label'] ?? a['mac']}' : '${r.resident} (${r.ringId})';
    final ts = ((a['ts'] as num?) ?? 0).toInt();
    final strong = color == V2.red || color == V2.orange;
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: r == null
            ? null
            : () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => ResidentScreen(mac: r.mac))),
        child: Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: strong ? color.withOpacity(.12) : V2.card,
            borderRadius: BorderRadius.circular(16),
          ),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Container(
              width: 40,
              height: 40,
              decoration: BoxDecoration(color: color.withOpacity(.18), shape: BoxShape.circle),
              child: Icon(icon, color: color, size: 24),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [
                  Expanded(
                    child: Text(title, style: TextStyle(color: color, fontWeight: FontWeight.w700, fontSize: 15)),
                  ),
                  Text(dayHm(ts), style: const TextStyle(color: C.muted, fontSize: 12)),
                ]),
                const SizedBox(height: 2),
                Text(who, style: const TextStyle(fontSize: 13.5)),
                Text('${a['message'] ?? ''}', style: const TextStyle(color: C.muted, fontSize: 12.5)),
              ]),
            ),
          ]),
        ),
      ),
    );
  }
}
