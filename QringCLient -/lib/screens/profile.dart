import 'package:flutter/material.dart';

import '../api.dart';
import '../i18n.dart';
import '../main.dart';
import '../push.dart';
import '../widgets.dart';

class ProfileScreen extends StatelessWidget {
  const ProfileScreen({super.key});

  Future<void> _password(BuildContext context) async {
    final oldC = TextEditingController();
    final newC = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: C.card,
        title: Text(tr('pr.password')),
        content: Column(mainAxisSize: MainAxisSize.min, children: [
          TextField(controller: oldC, obscureText: true, decoration: InputDecoration(labelText: tr('pr.old'))),
          TextField(controller: newC, obscureText: true, decoration: InputDecoration(labelText: tr('pr.new'))),
        ]),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: Text(tr('btn.cancel'))),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: Text(tr('btn.save'))),
        ],
      ),
    );
    if (ok != true || !context.mounted) return;
    try {
      await ModelScope.read(context).changePassword(oldC.text, newC.text);
      if (context.mounted) toast(context, tr('pr.pass_ok'), color: C.ok);
    } on ApiException catch (e) {
      if (context.mounted) toast(context, e.message, color: C.err);
    }
  }

  @override
  Widget build(BuildContext context) {
    final m = ModelScope.of(context);
    final u = m.user ?? {};
    final alertsOn = u['alertsEnabled'] != false;
    return ListView(
      padding: const EdgeInsets.fromLTRB(14, 10, 14, 20),
      children: [
        Text(tr('tab.profile'), style: const TextStyle(fontSize: 21, fontWeight: FontWeight.w800)),
        const SizedBox(height: 12),
        Panel(
          child: Column(children: [
            const Icon(Icons.account_circle, size: 56, color: C.muted),
            Text('${u['name'] ?? ''}', style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
            Text('${u['login'] ?? ''}', style: const TextStyle(color: C.muted)),
            const SizedBox(height: 4),
            Text(tr('pr.rings', [m.rings.length]), style: const TextStyle(color: C.muted, fontSize: 12)),
          ]),
        ),
        const SizedBox(height: 10),
        Panel(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(tr('pr.lang'), style: const TextStyle(color: C.muted, fontSize: 12)),
            const SizedBox(height: 6),
            Wrap(spacing: 6, children: [
              for (final l in const [('fr', 'Français'), ('en', 'English'), ('ar', 'العربية')])
                ChoiceChip(
                  label: Text(l.$2),
                  selected: appLang == l.$1,
                  onSelected: (_) => m.setPrefs({'lang': l.$1}).catchError((Object e) {
                    if (context.mounted) toast(context, '$e', color: C.err);
                  }),
                ),
            ]),
          ]),
        ),
        const SizedBox(height: 10),
        Panel(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              const Icon(Icons.notifications_outlined, color: C.muted),
              const SizedBox(width: 10),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(tr('pr.alerts'), style: const TextStyle(fontWeight: FontWeight.w600)),
                  Text(tr('pr.alerts_sub'), style: const TextStyle(color: C.muted, fontSize: 11)),
                ]),
              ),
              Switch(value: alertsOn, onChanged: (v) => m.setPrefs({'alerts_enabled': v}).catchError((Object e) {
                if (context.mounted) toast(context, '$e', color: C.err);
              })),
            ]),
            Padding(
              padding: const EdgeInsets.only(top: 4, bottom: 4),
              child: Text(Push.initialized && u['fcm'] == true ? tr('pr.notif_on') : tr('pr.notif_off'),
                  style: TextStyle(color: Push.initialized && u['fcm'] == true ? C.ok : C.muted, fontSize: 11)),
            ),
          ]),
        ),
        const SizedBox(height: 10),
        Panel(
          padding: EdgeInsets.zero,
          child: ListTile(
            leading: const Icon(Icons.key_outlined),
            title: Text(tr('pr.password')),
            onTap: () => _password(context),
          ),
        ),
        const SizedBox(height: 16),
        FilledButton.icon(
          onPressed: m.logout,
          icon: const Icon(Icons.logout),
          label: Text(tr('pr.logout')),
          style: FilledButton.styleFrom(
            backgroundColor: C.err.withOpacity(.18),
            foregroundColor: C.err,
            padding: const EdgeInsets.symmetric(vertical: 14),
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
          ),
        ),
        const SizedBox(height: 14),
        Text('Client RHM v1.0 · ${tr('pr.server', [m.api.server])}',
            textAlign: TextAlign.center, style: const TextStyle(color: C.muted, fontSize: 11)),
      ],
    );
  }
}
