import 'package:flutter/material.dart';

import '../api.dart';
import '../i18n.dart';
import '../main.dart';
import '../push.dart';
import '../v2.dart';
import '../widgets.dart';

/// V2 · écran 6 « Profil » : mon compte, établissement, paramètres (notifications, affichage, aide, à propos).
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

  void _display(BuildContext context) {
    final m = ModelScope.read(context);
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: C.card,
        title: Text(tr('v2.display')),
        content: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(tr('pr.lang'), style: const TextStyle(color: C.muted, fontSize: 12)),
          const SizedBox(height: 6),
          Wrap(spacing: 6, children: [
            for (final l in const [('fr', 'Français'), ('en', 'English'), ('ar', 'العربية')])
              ChoiceChip(
                label: Text(l.$2),
                selected: appLang == l.$1,
                onSelected: (_) {
                  Navigator.pop(ctx);
                  m.setPrefs({'lang': l.$1}).catchError((Object e) {
                    if (context.mounted) toast(context, '$e', color: C.err);
                  });
                },
              ),
          ]),
        ]),
        actions: [TextButton(onPressed: () => Navigator.pop(ctx), child: Text(tr('btn.close')))],
      ),
    );
  }

  void _info(BuildContext context, String title, String text) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: C.card,
        title: Text(title),
        content: Text(text),
        actions: [TextButton(onPressed: () => Navigator.pop(ctx), child: Text(tr('btn.ok')))],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final m = ModelScope.of(context);
    final u = m.user ?? {};
    final alertsOn = u['alertsEnabled'] != false;
    final now = m.serverNow();
    final detected = m.rings.where((r) => detectionOf(r, now).isDetected).length;

    Widget section(String t) => Padding(
          padding: const EdgeInsets.fromLTRB(2, 18, 2, 8),
          child: Text(t, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
        );
    Widget tile(IconData ic, String title, {String? sub, Widget? trailing, VoidCallback? onTap}) => ListTile(
          leading: Icon(ic, color: C.text),
          title: Text(title, style: const TextStyle(fontWeight: FontWeight.w600)),
          subtitle: sub == null ? null : Text(sub, style: const TextStyle(color: C.muted, fontSize: 12)),
          trailing: trailing ?? const Icon(Icons.chevron_right, color: C.muted),
          onTap: onTap,
        );
    BoxDecoration box() => BoxDecoration(color: V2.card, borderRadius: BorderRadius.circular(16));

    return ListView(
      padding: const EdgeInsets.fromLTRB(14, 12, 14, 20),
      children: [
        TabHeader(tr('tab.profile'), showLive: false),
        section(tr('v2.account')),
        Container(
          decoration: box(),
          child: ListTile(
            contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
            leading: const CircleAvatar(backgroundColor: C.card2, child: Icon(Icons.person, color: C.text)),
            title: Text('${u['name'] ?? u['login'] ?? ''}', style: const TextStyle(fontWeight: FontWeight.w700)),
            subtitle: Text('${u['login'] ?? ''} · ${tr('pr.password')}',
                style: const TextStyle(color: C.muted, fontSize: 12)),
            trailing: const Icon(Icons.chevron_right, color: C.muted),
            onTap: () => _password(context),
          ),
        ),
        section(tr('v2.org')),
        Container(
          padding: const EdgeInsets.all(12),
          decoration: box(),
          child: Row(children: [
            ClipRRect(
                borderRadius: BorderRadius.circular(12),
                child: Image.asset('assets/logo_epat.png', width: 64, height: 64, fit: BoxFit.cover)),
            const SizedBox(width: 14),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(tr('app.org'), style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15)),
                Text(tr('v2.org_residents', [m.rings.length]), style: const TextStyle(color: C.text)),
                Text(tr('v2.org_detected', [detected]), style: const TextStyle(color: C.muted, fontSize: 12.5)),
              ]),
            ),
          ]),
        ),
        section(tr('v2.settings')),
        Container(
          decoration: box(),
          child: Column(children: [
            tile(Icons.notifications, tr('v2.notifs'),
                sub: '${alertsOn ? tr('v2.on') : tr('v2.off')}'
                    '${Push.initialized && u['fcm'] == true ? '' : ' · ${tr('pr.notif_off')}'}',
                trailing: Switch(
                  value: alertsOn,
                  onChanged: (v) => m.setPrefs({'alerts_enabled': v}).catchError((Object e) {
                    if (context.mounted) toast(context, '$e', color: C.err);
                  }),
                )),
            const Divider(height: 1, color: C.line),
            tile(Icons.tune, tr('v2.display'), sub: tr('pr.lang'), onTap: () => _display(context)),
            const Divider(height: 1, color: C.line),
            tile(Icons.help_outline, tr('v2.help'), onTap: () => _info(context, tr('v2.help'), tr('v2.help_text'))),
            const Divider(height: 1, color: C.line),
            tile(Icons.info_outline, tr('v2.about'),
                sub: 'Client RHM v2.0',
                onTap: () => _info(context, tr('v2.about'), 'Client RHM v2.0\n${tr('pr.server', [m.api.server])}')),
          ]),
        ),
        const SizedBox(height: 22),
        OutlinedButton(
          onPressed: m.logout,
          style: OutlinedButton.styleFrom(
            padding: const EdgeInsets.symmetric(vertical: 14),
            side: const BorderSide(color: V2.red),
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
          ),
          child: Text(tr('pr.logout'), style: const TextStyle(color: V2.red, fontWeight: FontWeight.w700)),
        ),
      ],
    );
  }
}
