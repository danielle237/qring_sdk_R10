// QRingClient — app téléphone de suivi des bagues RHM.
// Passe par le service qring-client-api (indépendant de QRing Admin), qui écoute Mosquitto.
import 'dart:async';

import 'package:flutter/material.dart';

import 'i18n.dart';
import 'model.dart';
import 'push.dart';
import 'screens/alerts.dart';
import 'screens/login.dart';
import 'screens/profile.dart';
import 'screens/ring.dart';
import 'screens/rings.dart';
import 'widgets.dart';

final navKey = GlobalKey<NavigatorState>();

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Push.init();
  final model = AppModel();
  runApp(QRingClientApp(model: model));
  await model.init();
}

/// Donne accès au modèle partout (sans paquet supplémentaire).
class ModelScope extends InheritedNotifier<AppModel> {
  const ModelScope({super.key, required AppModel model, required super.child}) : super(notifier: model);
  static AppModel of(BuildContext context) => context.dependOnInheritedWidgetOfExactType<ModelScope>()!.notifier!;
  static AppModel read(BuildContext context) =>
      (context.getElementForInheritedWidgetOfExactType<ModelScope>()!.widget as ModelScope).notifier!;
}

class QRingClientApp extends StatelessWidget {
  final AppModel model;
  const QRingClientApp({super.key, required this.model});

  @override
  Widget build(BuildContext context) {
    return ModelScope(
      model: model,
      child: MaterialApp(
        navigatorKey: navKey,
        title: 'Client RHM',
        debugShowCheckedModeBanner: false,
        theme: ThemeData(
          brightness: Brightness.dark,
          scaffoldBackgroundColor: C.bg,
          colorScheme: const ColorScheme.dark(primary: C.accent, surface: C.surface, error: C.err),
          appBarTheme: const AppBarTheme(backgroundColor: C.bg, elevation: 0, centerTitle: false),
          useMaterial3: true,
        ),
        builder: (context, child) {
          // Langue arabe : écran de droite à gauche
          ModelScope.of(context); // reconstruit à chaque changement (langue…)
          return Directionality(
            textDirection: isRtl ? TextDirection.rtl : TextDirection.ltr,
            child: child!,
          );
        },
        home: const Root(),
      ),
    );
  }
}

class Root extends StatelessWidget {
  const Root({super.key});
  @override
  Widget build(BuildContext context) {
    final m = ModelScope.of(context);
    if (!m.ready) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    return m.loggedIn ? const HomeShell() : const LoginScreen();
  }
}

class HomeShell extends StatefulWidget {
  const HomeShell({super.key});
  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> {
  int tab = 0;
  StreamSubscription? _ui;
  StreamSubscription? _opened;

  @override
  void initState() {
    super.initState();
    final m = ModelScope.read(context);
    _ui = m.uiEvents.stream.listen(_onUi);
    _opened = Push.opened.stream.listen(_openRing);
    Push.initialMac().then((mac) {
      if (mac != null) _openRing(mac);
    });
  }

  @override
  void dispose() {
    _ui?.cancel();
    _opened?.cancel();
    super.dispose();
  }

  void _openRing(String mac) {
    if (!mounted) return;
    final m = ModelScope.read(context);
    final r = m.ringByMac(mac.toUpperCase());
    if (r == null) return;
    navKey.currentState?.push(MaterialPageRoute(builder: (_) => RingScreen(mac: r.mac)));
  }

  final Set<String> _backOpen = {};

  /// Popup centré « Content de vous revoir » : vérifier si la bague est portée (Oui / Plus tard).
  void _showBack(String mac) {
    final m = ModelScope.read(context);
    final r = m.ringByMac(mac);
    final ctx = navKey.currentContext;
    if (r == null || ctx == null || _backOpen.contains(mac)) return;
    _backOpen.add(mac);
    showDialog(
      context: ctx,
      builder: (dctx) => AlertDialog(
        backgroundColor: C.card,
        icon: const Icon(Icons.bluetooth_connected, color: C.ok, size: 44),
        title: Text(tr('pop.back_title'), textAlign: TextAlign.center),
        content: Text(tr('pop.back_text', [r.title]), textAlign: TextAlign.center),
        actionsAlignment: MainAxisAlignment.center,
        actions: [
          TextButton(onPressed: () => Navigator.pop(dctx), child: Text(tr('pop.back_later'))),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: C.ok, foregroundColor: Colors.black),
            onPressed: () {
              Navigator.pop(dctx);
              final cur = m.ringByMac(mac);
              if (cur != null) m.startCheck(cur);
            },
            child: Text(tr('pop.back_yes'), style: const TextStyle(fontWeight: FontWeight.w700)),
          ),
        ],
      ),
    ).whenComplete(() => _backOpen.remove(mac));
  }

  void _onUi(Map<String, dynamic> e) {
    if (!mounted) return;
    if (e['type'] == 'back') {
      _showBack(e['mac'] as String);
      return;
    }
    if (e['type'] == 'alert') {
      final a = e['alert'] as Map<String, dynamic>;
      // Retour de la bague : le popup centré suffit (l'alerte reste dans l'onglet Alertes)
      if (a['kind'] == 'restored_range' || a['kind'] == 'bound') return;
      final color = switch (a['kind']) {
        'removed' || 'unbound' => C.warn,
        'out_of_range' || 'gateway_offline' => C.err,
        'battery_low' => C.warn,
        _ => C.ok,
      };
      // Bandeau d'alerte : disparaît seul après 5 s (toucher = ouvrir la bague).
      // Pas de SnackBarAction : avec une action, Flutter garde le bandeau affiché.
      final sm = ScaffoldMessenger.of(context);
      sm.hideCurrentSnackBar();
      sm.showSnackBar(SnackBar(
        backgroundColor: color.withOpacity(.95),
        behavior: SnackBarBehavior.floating,
        duration: const Duration(seconds: 5),
        content: GestureDetector(
          onTap: () {
            sm.hideCurrentSnackBar();
            _openRing(a['mac'] as String);
          },
          child: Row(children: [
            Expanded(
              child: Text('${a['title']}\n${a['message']}',
                  style: const TextStyle(color: Colors.black, fontWeight: FontWeight.w600)),
            ),
            const Icon(Icons.chevron_right, color: Colors.black),
          ]),
        ),
      ));
    } else if (e['type'] == 'busy') {
      showDialog(
        context: context,
        builder: (ctx) => AlertDialog(
          backgroundColor: C.card,
          icon: const Icon(Icons.hourglass_top, color: C.accent, size: 40),
          title: Text(tr('pop.busy_title'), textAlign: TextAlign.center),
          content: Text(tr('pop.busy_text', [tr('btn.${e['cmd']}')]), textAlign: TextAlign.center),
          actions: [TextButton(onPressed: () => Navigator.pop(ctx), child: Text(tr('btn.ok')))],
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final m = ModelScope.of(context);
    final pages = [const RingsScreen(), const AlertsScreen(), const ProfileScreen()];
    return Scaffold(
      body: SafeArea(child: pages[tab]),
      bottomNavigationBar: NavigationBar(
        backgroundColor: C.surface,
        selectedIndex: tab,
        onDestinationSelected: (i) {
          setState(() => tab = i);
          if (i == 1) m.loadAlerts();
        },
        destinations: [
          NavigationDestination(icon: const Icon(Icons.radio_button_checked), label: tr('tab.rings')),
          NavigationDestination(icon: const Icon(Icons.notifications_outlined), label: tr('tab.alerts')),
          NavigationDestination(icon: const Icon(Icons.person_outline), label: tr('tab.profile')),
        ],
      ),
    );
  }
}
