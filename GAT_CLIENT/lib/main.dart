import 'dart:async';
import 'dart:math';

import 'package:flutter/material.dart';

import 'controller.dart';
import 'model.dart';
import 'net.dart';

const kBg = Color(0xFF0A1220);
const kCard = Color(0xFF111C2F);
const kLine = Color(0xFF233553);
const kTx = Color(0xFFE6EDF7);
const kMut = Color(0xFF8DA0BD);
const kBlue = Color(0xFF38BDF8);
const kGreen = Color(0xFF34D399);
const kOrange = Color(0xFFFBBF24);
const kRed = Color(0xFFF87171);

/// Journal d'erreurs affiché à l'écran (utile quand on ne voit pas la console).
class Diag {
  static final ValueNotifier<List<String>> log = ValueNotifier<List<String>>([]);
  static void add(String s) {
    final l = [...log.value, s];
    log.value = l.length > 8 ? l.sublist(l.length - 8) : l;
  }
}

void main() {
  runZonedGuarded(() {
    WidgetsFlutterBinding.ensureInitialized();
    FlutterError.onError = (d) {
      Diag.add('FlutterError: ${d.exceptionAsString()}');
      FlutterError.presentError(d);
    };
    ErrorWidget.builder = (d) => Container(
          color: const Color(0xFF3A0A0A),
          padding: const EdgeInsets.all(8),
          child: Text(
            d.exceptionAsString(),
            textDirection: TextDirection.ltr,
            style: const TextStyle(color: Colors.white, fontSize: 11),
          ),
        );
    runApp(const GatApp());
  }, (e, st) => Diag.add('Erreur: $e'));
}

class GatApp extends StatelessWidget {
  const GatApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Client RHM',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.dark,
        scaffoldBackgroundColor: kBg,
        colorScheme: const ColorScheme.dark(primary: kBlue, surface: kCard),
        useMaterial3: true,
      ),
      home: const Boot(),
    );
  }
}

/// Premier écran très simple : prouve que Flutter dessine, puis charge l'écran principal.
class Boot extends StatefulWidget {
  const Boot({super.key});

  @override
  State<Boot> createState() => _BootState();
}

class _BootState extends State<Boot> {
  bool ready = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      Future.delayed(const Duration(milliseconds: 400), () {
        if (mounted) setState(() => ready = true);
      });
    });
  }

  @override
  Widget build(BuildContext context) {
    return Stack(children: [
      ready
          ? const HomePage()
          : const Scaffold(
              body: Center(
                child: Text('Client RHM — démarrage…', style: TextStyle(color: kTx, fontSize: 18)),
              ),
            ),
      Positioned(
        left: 0,
        right: 0,
        bottom: 0,
        child: ValueListenableBuilder<List<String>>(
          valueListenable: Diag.log,
          builder: (context, l, _) {
            if (l.isEmpty) return const SizedBox.shrink();
            return Material(
              color: const Color(0xEE3A0A0A),
              child: SafeArea(
                top: false,
                child: Padding(
                  padding: const EdgeInsets.all(8),
                  child: Text(l.join('\n'), style: const TextStyle(color: Colors.white, fontSize: 10)),
                ),
              ),
            );
          },
        ),
      ),
    ]);
  }
}

class HomePage extends StatefulWidget {
  const HomePage({super.key});

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  final ctl = Controller();

  @override
  void initState() {
    super.initState();
    ctl.start().catchError((Object e) {
      Diag.add('start: $e');
    });
  }

  @override
  void dispose() {
    ctl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: ctl,
      builder: (context, _) {
        final t = ctl.toast;
        if (t != null) {
          ctl.clearToast();
          WidgetsBinding.instance.addPostFrameCallback((_) {
            if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(t)));
          });
        }
        return Scaffold(
          body: SafeArea(
            child: LayoutBuilder(builder: (context, box) {
              final wide = box.maxWidth >= 900;
              final map = _MapCard(ctl: ctl);
              final side = Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                _StateCard(ctl: ctl),
                _GattCard(ctl: ctl),
                _GatewaysCard(ctl: ctl),
              ]);
              return SingleChildScrollView(
                padding: const EdgeInsets.all(16),
                child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                  _Header(ctl: ctl),
                  const SizedBox(height: 12),
                  if (wide)
                    Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Expanded(flex: 3, child: map),
                      const SizedBox(width: 16),
                      SizedBox(width: 360, child: side),
                    ])
                  else ...[map, const SizedBox(height: 12), side],
                  const SizedBox(height: 12),
                  _TechCard(ctl: ctl),
                ]),
              );
            }),
          ),
        );
      },
    );
  }
}

// ---------------------------------------------------------------------- composants communs

class _Card extends StatelessWidget {
  final String? title;
  final String? subtitle;
  final Widget child;
  final Widget? trailing;
  const _Card({this.title, this.subtitle, required this.child, this.trailing});

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: kCard,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: kLine),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        if (title != null)
          Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
            Expanded(child: Text(title!, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700, color: kTx))),
            if (trailing != null) trailing!,
          ]),
        if (subtitle != null)
          Padding(
            padding: const EdgeInsets.only(top: 2),
            child: Text(subtitle!, style: const TextStyle(fontSize: 11, color: kMut)),
          ),
        if (title != null) const SizedBox(height: 10),
        child,
      ]),
    );
  }
}

class _Chip extends StatelessWidget {
  final String text;
  final Color color;
  const _Chip(this.text, this.color);

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 2),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(99),
        border: Border.all(color: color),
      ),
      child: Text(text, style: TextStyle(color: color, fontSize: 11, fontWeight: FontWeight.w600)),
    );
  }
}

class _Pill extends StatelessWidget {
  final String text;
  final VoidCallback? onTap;
  final Color? color;
  const _Pill(this.text, {this.onTap, this.color});

  @override
  Widget build(BuildContext context) {
    return InkWell(
      borderRadius: BorderRadius.circular(99),
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        decoration: BoxDecoration(
          color: kCard,
          borderRadius: BorderRadius.circular(99),
          border: Border.all(color: color ?? kLine),
        ),
        child: Text(text, style: TextStyle(fontSize: 12, color: color ?? kTx, fontWeight: color == null ? FontWeight.w400 : FontWeight.w700)),
      ),
    );
  }
}

String _ago(DateTime? t) {
  if (t == null) return '—';
  final s = DateTime.now().difference(t).inSeconds;
  if (s < 60) return 'il y a $s s';
  if (s < 3600) return 'il y a ${s ~/ 60} min';
  return 'il y a ${s ~/ 3600} h';
}

// ---------------------------------------------------------------------- en-tete

class _Header extends StatelessWidget {
  final Controller ctl;
  const _Header({required this.ctl});

  @override
  Widget build(BuildContext context) {
    final rx = ctl.lastRx == null ? 'en attente des gateways…' : 'dernier message ${_ago(ctl.lastRx)}';
    final connected = ctl.lastRx != null && DateTime.now().difference(ctl.lastRx!).inSeconds <= 15;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      const Text('Client RHM — Live Ring Map', style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800, color: kTx)),
      const Text('Couverture BLE locale, gateways candidates et zone probable', style: TextStyle(fontSize: 12, color: kMut)),
      const Text(
        'Informations de santé et de bien-être à caractère indicatif — non diagnostiques.',
        style: TextStyle(fontSize: 11, color: kOrange, fontWeight: FontWeight.w600),
      ),
      const SizedBox(height: 10),
      Wrap(spacing: 8, runSpacing: 8, children: [
        _Pill(connected ? 'CONNECTÉ' : 'DÉCONNECTÉ', color: connected ? kGreen : kRed),
        _Pill('Paquets reçus : ${ctl.net.rx}${ctl.net.interfaces.isEmpty ? '' : ' · ${ctl.net.interfaces.join(', ')}'}'),
        _Pill('UDP multicast: ${Net.obsGroup}:${Net.obsPort}'),
        _Pill('Site: ${ctl.site}', onTap: () => _editSite(context)),
        _Pill(rx),
        if (ctl.net.error != null) _Pill('Erreur réseau : ${ctl.net.error}'),
      ]),
    ]);
  }

  Future<void> _editSite(BuildContext context) async {
    final c = TextEditingController(text: ctl.site);
    final v = await showDialog<String>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Nom du site'),
        content: TextField(controller: c, autofocus: true),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Annuler')),
          TextButton(onPressed: () => Navigator.pop(context, c.text.trim()), child: const Text('OK')),
        ],
      ),
    );
    if (v != null && v.isNotEmpty) ctl.setSite(v);
  }
}

// ---------------------------------------------------------------------- carte

class _MapCard extends StatefulWidget {
  final Controller ctl;
  const _MapCard({required this.ctl});

  @override
  State<_MapCard> createState() => _MapCardState();
}

class _MapCardState extends State<_MapCard> {
  String? dragging;

  @override
  Widget build(BuildContext context) {
    final ctl = widget.ctl;
    final ring = ctl.selectedRing;
    final cands = ring == null ? <Obs>[] : ctl.table.candidates(ring);
    final rssi = {for (final o in cands) o.gw: o.rssi!};
    final zones = ctl.cfg.values.map((c) => c.zone).where((z) => z.isNotEmpty).toSet().join(' / ');

    return _Card(
      title: zones.isEmpty ? 'Carte des zones' : zones,
      subtitle: 'Position visuelle lissée (EMA) — estimation de zone, sans modifier les données techniques',
      trailing: Row(mainAxisSize: MainAxisSize.min, children: [
        const Text('Déplacer', style: TextStyle(fontSize: 11, color: kMut)),
        Switch(value: ctl.editMode, onChanged: ctl.setEditMode),
      ]),
      child: Column(children: [
        AspectRatio(
          aspectRatio: 1.7,
          child: LayoutBuilder(builder: (context, box) {
            final size = Size(box.maxWidth, box.maxHeight);
            return GestureDetector(
              onTapUp: ctl.editMode
                  ? null
                  : (d) {
                      final g = _nearest(d.localPosition, size);
                      if (g != null) showGatewaySheet(context, ctl, g);
                    },
              onPanStart: ctl.editMode ? (d) => dragging = _nearest(d.localPosition, size) : null,
              onPanUpdate: ctl.editMode
                  ? (d) {
                      final g = dragging;
                      if (g != null) ctl.moveGateway(g, d.localPosition.dx / size.width * 100, d.localPosition.dy / size.height * 100);
                    }
                  : null,
              onPanEnd: ctl.editMode ? (_) => dragging = null : null,
              child: ClipRRect(
                borderRadius: BorderRadius.circular(12),
                child: CustomPaint(
                  size: size,
                  painter: _MapPainter(
                    gws: ctl.cfg.values.map((c) => GwCfg(c.name, c.zone, c.x, c.y)).toList(),
                    pos: ctl.pos ?? ctl.lastStablePos,
                    radius: ctl.radius,
                    localized: ctl.localized,
                    rssi: rssi,
                    best: ctl.stickyGw,
                    edit: ctl.editMode,
                  ),
                ),
              ),
            );
          }),
        ),
        const SizedBox(height: 8),
        const Wrap(spacing: 14, runSpacing: 4, children: [
          _Legend('candidate n°1', kBlue),
          _Legend('gateway qui voit la bague', kGreen),
          _Legend('non joignable / périmée', kMut),
          _Legend('cercle pointillé = incertitude', kOrange),
        ]),
        const SizedBox(height: 8),
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(10),
          decoration: BoxDecoration(
            color: const Color(0xFF0F1A2C),
            borderRadius: BorderRadius.circular(10),
            border: const Border(left: BorderSide(color: kBlue, width: 3)),
          ),
          child: const Text(
            'La position affichée est une estimation de zone. Le cercle pointillé matérialise l’incertitude : '
            'plus il est grand, moins la position est sûre.',
            style: TextStyle(fontSize: 11, color: kMut),
          ),
        ),
      ]),
    );
  }

  String? _nearest(Offset p, Size size) {
    String? best;
    double bd = 40;
    for (final g in widget.ctl.cfg.values) {
      final d = (Offset(g.x / 100 * size.width, g.y / 100 * size.height) - p).distance;
      if (d < bd) {
        bd = d;
        best = g.name;
      }
    }
    return best;
  }
}

class _Legend extends StatelessWidget {
  final String text;
  final Color color;
  const _Legend(this.text, this.color);

  @override
  Widget build(BuildContext context) {
    return Row(mainAxisSize: MainAxisSize.min, children: [
      Container(width: 8, height: 8, decoration: BoxDecoration(color: color, shape: BoxShape.circle)),
      const SizedBox(width: 5),
      Text(text, style: const TextStyle(fontSize: 11, color: kMut)),
    ]);
  }
}

class _MapPainter extends CustomPainter {
  final List<GwCfg> gws;
  final Offset? pos;
  final double radius;
  final bool localized;
  final Map<String, double> rssi;
  final String? best;
  final bool edit;

  _MapPainter({
    required this.gws,
    required this.pos,
    required this.radius,
    required this.localized,
    required this.rssi,
    required this.best,
    required this.edit,
  });

  void _text(Canvas c, String t, Offset center, double fs, Color col, {FontWeight w = FontWeight.w500}) {
    final tp = TextPainter(
      text: TextSpan(text: t, style: TextStyle(fontSize: fs, color: col, fontWeight: w)),
      textDirection: TextDirection.ltr,
    )..layout();
    tp.paint(c, center - Offset(tp.width / 2, tp.height / 2));
  }

  @override
  void paint(Canvas canvas, Size size) {
    if (size.isEmpty || !size.width.isFinite || !size.height.isFinite) return;
    final rect = Offset.zero & size;
    canvas.drawRect(
      rect,
      Paint()
        ..shader = const LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [Color(0xFF0C1A2E), Color(0xFF0B2745)],
        ).createShader(rect),
    );
    final grid = Paint()
      ..color = const Color(0x1438BDF8)
      ..strokeWidth = 1;
    for (int i = 0; i <= 20; i++) {
      final x = size.width * i / 20;
      canvas.drawLine(Offset(x, 0), Offset(x, size.height), grid);
    }
    for (int i = 0; i <= 11; i++) {
      final y = size.height * i / 11;
      canvas.drawLine(Offset(0, y), Offset(size.width, y), grid);
    }

    Offset at(double x, double y) => Offset(x / 100 * size.width, y / 100 * size.height);

    // Noms de zones en filigrane
    for (final g in gws) {
      if (g.zone.isEmpty) continue;
      final p = at(g.x, g.y);
      final up = g.y > 50 ? 0.12 * size.height : -0.14 * size.height;
      _text(canvas, g.zone.toUpperCase(), p + Offset(0, up), size.height * 0.1, const Color(0x2E8DA0BD), w: FontWeight.w900);
    }

    // Gateways
    for (final g in gws) {
      final p = at(g.x, g.y);
      final seeing = rssi.containsKey(g.name);
      final isBest = g.name == best && seeing;
      final col = isBest ? kBlue : (seeing ? kGreen : kMut);
      canvas.drawCircle(p, 14, Paint()..color = col.withOpacity(0.15));
      canvas.drawCircle(p, 8, Paint()..color = kBg);
      canvas.drawCircle(
        p,
        8,
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = 2
          ..color = col,
      );
      _text(canvas, g.name, p + const Offset(0, 22), 10, kTx, w: FontWeight.w700);
      if (g.zone.isNotEmpty) _text(canvas, g.zone, p + const Offset(0, 34), 9, kMut);
      _text(canvas, seeing ? '${rssi[g.name]!.round()} dBm' : '—', p + const Offset(0, 45), 9, col);
      if (edit) {
        canvas.drawCircle(
          p,
          18,
          Paint()
            ..style = PaintingStyle.stroke
            ..color = kOrange
            ..strokeWidth = 1,
        );
      }
    }

    // Bague
    final bp = pos;
    if (bp != null) {
      final c = at(bp.dx, bp.dy);
      final col = localized ? kGreen : kRed;
      final r = radius / 100 * size.width;
      final dash = Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1.5
        ..color = localized ? kOrange : kRed.withOpacity(0.7);
      const n = 28;
      for (int i = 0; i < n; i++) {
        canvas.drawArc(Rect.fromCircle(center: c, radius: r), i * 2 * pi / n, pi / n, false, dash);
      }
      canvas.drawCircle(c, 9, Paint()..color = col.withOpacity(0.25));
      canvas.drawCircle(c, 6, Paint()..color = col);
      if (!localized) {
        _text(canvas, 'SIGNAL PERDU', c + const Offset(0, 22), 11, kRed, w: FontWeight.w800);
        _text(canvas, 'dernière position approx.', c + const Offset(0, 34), 9, kMut);
      }
    }

    // Cadre
    canvas.drawRRect(
      RRect.fromRectAndRadius(rect.deflate(0.5), const Radius.circular(12)),
      Paint()
        ..style = PaintingStyle.stroke
        ..color = kLine,
    );
  }

  @override
  bool shouldRepaint(covariant _MapPainter old) => true;
}

// ---------------------------------------------------------------------- etat de la bague

class _StateCard extends StatelessWidget {
  final Controller ctl;
  const _StateCard({required this.ctl});

  @override
  Widget build(BuildContext context) {
    final rings = ctl.table.rings;
    final ring = ctl.selectedRing;
    final cands = ring == null ? <Obs>[] : ctl.table.candidates(ring);
    final best = cands.isEmpty ? null : cands.first;

    Widget body;
    if (ring == null) {
      body = const Text('En attente des observations multicast…', style: TextStyle(color: kMut));
    } else {
      body = Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        if (rings.length > 1)
          DropdownButton<String>(
            value: rings.contains(ring) ? ring : null,
            isExpanded: true,
            items: [for (final r in rings) DropdownMenuItem(value: r, child: Text(r))],
            onChanged: (v) {
              if (v != null) ctl.selectRing(v);
            },
          )
        else
          Text(ring, style: const TextStyle(color: kTx, fontWeight: FontWeight.w700)),
        const SizedBox(height: 8),
        if (ctl.localized && best != null) ...[
          Row(children: [
            const _Chip('DÉTECTÉE', kGreen),
            const SizedBox(width: 8),
            Text('Zone probable : ${ctl.currentZone ?? '—'}', style: const TextStyle(color: kTx, fontWeight: FontWeight.w700)),
          ]),
          const SizedBox(height: 6),
          Text('Gateway : ${ctl.stickyGw ?? best.gw} · ${best.rssi!.round()} dBm · ${_ago(best.recv)}',
              style: const TextStyle(color: kMut, fontSize: 12)),
        ] else ...[
          const _Chip('NON DÉTECTÉE', kRed),
          const SizedBox(height: 6),
          const Text('Zone actuelle inconnue', style: TextStyle(color: kTx, fontWeight: FontWeight.w700)),
          Text(
            ctl.lastZone == null ? 'Aucune détection récente.' : 'Dernière détection : ${ctl.lastZone} · ${_ago(ctl.lastSeenAt)}',
            style: const TextStyle(color: kMut, fontSize: 12),
          ),
          const Text('La batterie n’est pas connue : ne pas conclure « déchargée ».', style: TextStyle(color: kMut, fontSize: 11)),
        ],
      ]);
    }
    return _Card(title: 'État de la bague', subtitle: 'Vue synthétique', child: body);
  }
}

// ---------------------------------------------------------------------- mesure GATT

class _GattCard extends StatelessWidget {
  final Controller ctl;
  const _GattCard({required this.ctl});

  @override
  Widget build(BuildContext context) {
    final g = ctl.gatt;
    final measuring = ctl.measuring;
    final busy = ctl.busyElsewhere;

    String label;
    Color col;
    switch (g.functional ?? (measuring ? 'RUN' : 'IDLE')) {
      case 'SUCCESS':
        label = 'SUCCÈS';
        col = kGreen;
        break;
      case 'CONNECTED_NOT_WORN':
        label = 'CONNECTÉE / NON PORTÉE';
        col = kOrange;
        break;
      case 'OUT_OF_RANGE':
        label = 'HORS PORTÉE';
        col = kRed;
        break;
      case 'BUSY':
        label = 'GATEWAY OCCUPÉE';
        col = kOrange;
        break;
      case 'ERROR':
        label = 'ERREUR TECHNIQUE';
        col = kRed;
        break;
      case 'RUN':
        label = _statusLabel(g.status);
        col = kOrange;
        break;
      default:
        label = busy ? 'MESURE EN COURS (AUTRE CLIENT)' : 'PRÊT';
        col = busy ? kOrange : kBlue;
    }

    final canMeasure = !measuring && !busy && ctl.localized;
    final ring = ctl.selectedRing;
    final cands = ring == null ? <Obs>[] : ctl.table.candidates(ring);
    final chosenValid = ctl.chosenGw != null && cands.any((o) => o.gw == ctl.chosenGw);
    return _Card(
      title: 'Mesure GATT locale',
      trailing: _Chip(label, col),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(
          g.value != null ? '${g.value} bpm' : '—',
          style: const TextStyle(fontSize: 34, fontWeight: FontWeight.w800, color: kTx),
        ),
        if (g.at != null && g.done && g.functional == 'SUCCESS')
          Text('${g.gateway ?? ''} · mesure ${_ago(g.at)}', style: const TextStyle(color: kMut, fontSize: 11)),
        const SizedBox(height: 8),
        Row(children: [
          Expanded(child: _Tile('BATTERIE', g.battery == null ? '—' : '${g.battery} %')),
          const SizedBox(width: 8),
          Expanded(child: _Tile('CHARGE', g.charging == null ? '—' : (g.charging! ? 'en charge' : 'non'))),
        ]),
        if (g.reason != null && g.reason != 'null' && g.functional != 'SUCCESS')
          Padding(padding: const EdgeInsets.only(top: 6), child: Text(g.reason!, style: const TextStyle(color: kMut, fontSize: 11))),
        const SizedBox(height: 10),
        if (measuring) ...[
          Row(children: [
            const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)),
            const SizedBox(width: 10),
            Expanded(
              child: Text('${_statusLabel(g.status)} · ${g.gateway ?? ''}',
                  style: const TextStyle(color: kOrange, fontSize: 12, fontWeight: FontWeight.w600)),
            ),
          ]),
          const SizedBox(height: 6),
          const LinearProgressIndicator(minHeight: 3),
          const SizedBox(height: 10),
        ],
        DropdownButton<String>(
          isExpanded: true,
          value: chosenValid ? ctl.chosenGw : '__auto__',
          items: [
            const DropdownMenuItem(value: '__auto__', child: Text('Gateway : automatique (meilleur signal)')),
            for (final o in cands) DropdownMenuItem(value: o.gw, child: Text('${o.gw} · ${o.rssi!.round()} dBm')),
          ],
          onChanged: measuring ? null : (v) => ctl.setChosenGw(v == '__auto__' ? null : v),
        ),
        const SizedBox(height: 6),
        SizedBox(
          width: double.infinity,
          child: FilledButton(
            onPressed: canMeasure ? () => ctl.measure() : null,
            child: Text(measuring ? 'MESURE EN COURS…' : 'MESURER'),
          ),
        ),
        const SizedBox(height: 6),
        const Text(
          'La mesure est envoyée à la gateway au meilleur signal. Une seule mesure à la fois par bague.',
          style: TextStyle(color: kMut, fontSize: 11),
        ),
      ]),
    );
  }

  static String _statusLabel(String s) {
    switch (s) {
      case 'REQUESTED':
        return 'DEMANDÉE';
      case 'ACCEPTED':
        return 'ACCEPTÉE';
      case 'CONNECTING':
        return 'CONNEXION…';
      case 'CONNECTED':
        return 'CONNECTÉE';
      case 'MEASURING':
        return 'MESURE EN COURS';
      default:
        return s;
    }
  }
}

class _Tile extends StatelessWidget {
  final String label;
  final String value;
  const _Tile(this.label, this.value);

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: const Color(0xFF0F1A2C),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: kLine),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(label, style: const TextStyle(fontSize: 10, color: kMut)),
        const SizedBox(height: 2),
        Text(value, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700, color: kTx)),
      ]),
    );
  }
}

// ---------------------------------------------------------------------- gateways

class _GatewaysCard extends StatelessWidget {
  final Controller ctl;
  const _GatewaysCard({required this.ctl});

  @override
  Widget build(BuildContext context) {
    final ring = ctl.selectedRing;
    final obs = ring == null ? <String, Obs>{} : {for (final o in ctl.table.all(ring)) o.gw: o};
    final gws = ctl.cfg.values.toList()..sort((a, b) => a.name.compareTo(b.name));

    return _Card(
      title: 'Gateways',
      child: gws.isEmpty
          ? const Text('Pas de gateway connue', style: TextStyle(color: kMut))
          : Column(children: [
              for (final g in gws)
                InkWell(
                  onTap: ctl.editMode ? () => _rename(context, g) : () => showGatewaySheet(context, ctl, g.name),
                  child: Padding(
                    padding: const EdgeInsets.symmetric(vertical: 6),
                    child: Row(children: [
                      Expanded(
                        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          Text(g.name, style: const TextStyle(color: kTx, fontWeight: FontWeight.w600, fontSize: 13)),
                          Text(g.zone.isEmpty ? 'zone non définie' : g.zone, style: const TextStyle(color: kMut, fontSize: 11)),
                        ]),
                      ),
                      _status(obs[g.name]),
                    ]),
                  ),
                ),
              if (ctl.editMode)
                const Padding(
                  padding: EdgeInsets.only(top: 6),
                  child: Text('Touchez une gateway pour renommer sa zone ; faites-la glisser sur la carte pour la placer.',
                      style: TextStyle(color: kMut, fontSize: 11)),
                ),
            ]),
    );
  }

  Widget _status(Obs? o) {
    if (o == null) return const _Chip('inconnue', kMut);
    if (o.ageS > RingTable.ttlS) return const _Chip('périmée', kMut);
    if (!o.reachable || o.rssi == null) return _Chip(o.status ?? 'non joignable', kRed);
    return _Chip('${o.rssi!.round()} dBm', kGreen);
  }

  Future<void> _rename(BuildContext context, GwCfg g) async {
    final c = TextEditingController(text: g.zone);
    final v = await showDialog<String>(
      context: context,
      builder: (_) => AlertDialog(
        title: Text('Zone de ${g.name}'),
        content: TextField(controller: c, autofocus: true),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Annuler')),
          TextButton(onPressed: () => Navigator.pop(context, c.text.trim()), child: const Text('OK')),
        ],
      ),
    );
    if (v != null) ctl.renameZone(g.name, v);
  }
}

// ---------------------------------------------------------------------- vue technique

class _TechCard extends StatelessWidget {
  final Controller ctl;
  const _TechCard({required this.ctl});

  @override
  Widget build(BuildContext context) {
    final rows = <DataRow>[];
    for (final ring in ctl.table.rings) {
      for (final o in ctl.table.all(ring)) {
        final fresh = o.ageS <= RingTable.ttlS;
        final state = !fresh ? 'STALE' : (o.reachable ? 'REACHABLE' : (o.status ?? 'NOT_AVAILABLE'));
        rows.add(DataRow(cells: [
          DataCell(Text(ring)),
          DataCell(Text(o.gw)),
          DataCell(Text(o.ip ?? '—')),
          DataCell(Text(state)),
          DataCell(Text(o.rssi == null ? '—' : '${o.rssi!.round()} dBm')),
          DataCell(Text('${o.ageS.toStringAsFixed(1)} s')),
          DataCell(Text('${o.seq ?? '—'}')),
        ]));
      }
    }
    return _Card(
      title: 'Vue technique détaillée',
      subtitle: 'Données reçues directement depuis le multicast LAN',
      child: rows.isEmpty
          ? const Text('En attente…', style: TextStyle(color: kMut))
          : SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: DataTable(
                headingTextStyle: const TextStyle(color: kMut, fontSize: 11),
                dataTextStyle: const TextStyle(color: kTx, fontSize: 12),
                columns: const [
                  DataColumn(label: Text('Ring')),
                  DataColumn(label: Text('Gateway')),
                  DataColumn(label: Text('IP')),
                  DataColumn(label: Text('État')),
                  DataColumn(label: Text('RSSI')),
                  DataColumn(label: Text('Âge')),
                  DataColumn(label: Text('Seq')),
                ],
                rows: rows,
              ),
            ),
    );
  }
}

// ---------------------------------------------------------------------- menu d'une gateway

/// Feuille qui s'ouvre quand on touche une gateway : liste des mesures qu'on peut lui demander.
void showGatewaySheet(BuildContext context, Controller ctl, String gw) {
  showModalBottomSheet<void>(
    context: context,
    backgroundColor: kCard,
    builder: (ctx) {
      final cfg = ctl.cfg[gw];
      final ring = ctl.selectedRing;
      final sees = ring != null && ctl.table.candidates(ring).any((o) => o.gw == gw);
      final busy = ctl.measuring || ctl.busyElsewhere;
      return SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(gw, style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800, color: kTx)),
            Text(
              (cfg == null || cfg.zone.isEmpty) ? 'zone non définie' : cfg.zone,
              style: const TextStyle(color: kMut, fontSize: 12),
            ),
            const SizedBox(height: 12),
            const Text('Mesures disponibles', style: TextStyle(color: kMut, fontSize: 12)),
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.favorite, color: kRed),
              title: const Text('Fréquence cardiaque (HR)'),
              subtitle: Text(
                ring == null
                    ? 'Aucune bague détectée'
                    : !sees
                        ? 'Cette gateway ne voit pas la bague'
                        : busy
                            ? 'Une mesure est déjà en cours'
                            : 'Mesure du cœur et de la batterie, environ 30 s',
              ),
              enabled: sees && !busy,
              onTap: () {
                Navigator.pop(ctx);
                ctl.measure(gateway: gw);
              },
            ),
          ]),
        ),
      );
    },
  );
}
