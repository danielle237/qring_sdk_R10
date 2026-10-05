import 'package:flutter/material.dart';

import '../api.dart';
import '../i18n.dart';
import '../main.dart';
import '../widgets.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});
  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _user = TextEditingController();
  final _pass = TextEditingController();
  final _server = TextEditingController();
  bool keep = true;
  bool busy = false;
  bool hide = true;
  bool showServer = false;
  String? error;

  @override
  void initState() {
    super.initState();
    final m = ModelScope.read(context);
    _user.text = m.lastLogin;
    _server.text = m.api.server;
  }

  Future<void> _go() async {
    if (_user.text.trim().isEmpty || _pass.text.isEmpty) return;
    setState(() {
      busy = true;
      error = null;
    });
    try {
      await ModelScope.read(context).login(_user.text, _pass.text, keep, _server.text);
    } on ApiException catch (e) {
      if (mounted) setState(() => error = e.message);
    } catch (e) {
      if (mounted) setState(() => error = '$e');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  InputDecoration _dec(String label, IconData icon, {Widget? suffix}) => InputDecoration(
        labelText: label,
        prefixIcon: Icon(icon, color: C.muted),
        suffixIcon: suffix,
        filled: true,
        fillColor: C.card,
        border: OutlineInputBorder(borderRadius: BorderRadius.circular(14), borderSide: BorderSide.none),
      );

  @override
  Widget build(BuildContext context) {
    ModelScope.of(context);
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                Center(
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(26),
                    child: Image.asset('assets/icon.png', width: 116, height: 116),
                  ),
                ),
                const SizedBox(height: 14),
                const Text('Client RHM', textAlign: TextAlign.center,
                    style: TextStyle(fontSize: 26, fontWeight: FontWeight.w800, color: C.text)),
                Text(tr('app.sub'), textAlign: TextAlign.center, style: const TextStyle(color: C.muted)),
                const SizedBox(height: 28),
                TextField(
                  controller: _user,
                  autocorrect: false,
                  textInputAction: TextInputAction.next,
                  decoration: _dec(tr('login.user'), Icons.person_outline),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _pass,
                  obscureText: hide,
                  onSubmitted: (_) => _go(),
                  decoration: _dec(tr('login.pass'), Icons.lock_outline,
                      suffix: IconButton(
                        icon: Icon(hide ? Icons.visibility : Icons.visibility_off, color: C.muted),
                        onPressed: () => setState(() => hide = !hide),
                      )),
                ),
                CheckboxListTile(
                  value: keep,
                  onChanged: (v) => setState(() => keep = v ?? true),
                  title: Text(tr('login.keep'), style: const TextStyle(color: C.muted)),
                  controlAffinity: ListTileControlAffinity.leading,
                  contentPadding: EdgeInsets.zero,
                ),
                if (error != null)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 10),
                    child: Text(error!, textAlign: TextAlign.center, style: const TextStyle(color: C.err)),
                  ),
                FilledButton(
                  onPressed: busy ? null : _go,
                  style: FilledButton.styleFrom(
                      padding: const EdgeInsets.symmetric(vertical: 15),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14))),
                  child: busy
                      ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2))
                      : Text(tr('login.go'), style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
                ),
                const SizedBox(height: 18),
                Text(tr('login.admin'), textAlign: TextAlign.center, style: const TextStyle(color: C.muted, fontSize: 12)),
                TextButton(
                  onPressed: () => setState(() => showServer = !showServer),
                  child: Text(tr('login.server_adv'), style: const TextStyle(color: C.muted, fontSize: 12)),
                ),
                if (showServer)
                  TextField(
                    controller: _server,
                    keyboardType: TextInputType.url,
                    autocorrect: false,
                    decoration: _dec(tr('login.server'), Icons.dns_outlined),
                  ),
                const SizedBox(height: 10),
                Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                  for (final l in const [('fr', 'FR'), ('en', 'EN'), ('ar', 'العربية')])
                    TextButton(
                      onPressed: () => ModelScope.read(context).setLocalLang(l.$1),
                      child: Text(l.$2,
                          style: TextStyle(
                              color: appLang == l.$1 ? C.accent : C.muted,
                              fontWeight: appLang == l.$1 ? FontWeight.w700 : FontWeight.w400)),
                    ),
                ]),
              ]),
            ),
          ),
        ),
      ),
    );
  }
}
