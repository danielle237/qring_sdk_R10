import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/services.dart';

/// UDP multicast, meme protocole que la page "Live Ring Map" et GAT_ANDROID :
///  - 239.10.10.10:5010  presence (OBS) des gateways, en reception
///  - 239.10.10.12:5012  commandes (GATT_CMD), en emission
///  - 239.10.10.13:5013  statut / resultat de mesure (GATT_STATUS, GATT_RESULT), en reception
class Net {
  static const obsGroup = '239.10.10.10';
  static const obsPort = 5010;
  static const cmdGroup = '239.10.10.12';
  static const cmdPort = 5012;
  static const resGroup = '239.10.10.13';
  static const resPort = 5013;

  static const _channel = MethodChannel('gat/multicast');

  RawDatagramSocket? _obs;
  RawDatagramSocket? _res;
  RawDatagramSocket? _send;
  final _ctl = StreamController<Map<String, dynamic>>.broadcast();

  Stream<Map<String, dynamic>> get messages => _ctl.stream;

  /// Message d'erreur de demarrage, null si tout va bien.
  String? error;

  /// Nombre de paquets UDP recus (tous canaux) et interfaces reseau utilisees.
  int rx = 0;
  final List<String> interfaces = [];
  bool get running => _obs != null;

  Future<void> start() async {
    if (running) return;
    try {
      // Android : verrou multicast Wi-Fi (sinon les paquets multicast sont filtres)
      if (Platform.isAndroid) {
        try {
          await _channel.invokeMethod('acquire');
        } catch (_) {}
      }
      _obs = await _bind(obsGroup, obsPort);
      _res = await _bind(resGroup, resPort);
      _send = await RawDatagramSocket.bind(InternetAddress.anyIPv4, 0);
      _send!.multicastHops = 1;
      // Emission par l'interface Wi-Fi / Ethernet (et non la donnee mobile)
      try {
        final ifs = await NetworkInterface.list(type: InternetAddressType.IPv4, includeLoopback: false);
        final pref = ifs.where((i) => i.name.startsWith('wlan') || i.name.startsWith('eth') || i.name.startsWith('en'));
        if (pref.isNotEmpty) (_send as dynamic).multicastInterface = pref.first;
      } catch (_) {}
      error = null;
    } catch (e) {
      error = e.toString();
      await stop();
    }
  }

  Future<RawDatagramSocket> _bind(String group, int port) async {
    final s = await RawDatagramSocket.bind(
      InternetAddress.anyIPv4,
      port,
      reuseAddress: true,
      reusePort: !Platform.isWindows,
    );
    // Rejoint le groupe sur chaque interface reseau (sinon Android peut choisir la mauvaise)
    var joined = false;
    try {
      final ifs = await NetworkInterface.list(type: InternetAddressType.IPv4, includeLoopback: false);
      for (final i in ifs) {
        try {
          s.joinMulticast(InternetAddress(group), i);
          joined = true;
          if (!interfaces.contains(i.name)) interfaces.add(i.name);
        } catch (_) {}
      }
    } catch (_) {}
    if (!joined) s.joinMulticast(InternetAddress(group));
    s.listen((event) {
      if (event != RawSocketEvent.read) return;
      final d = s.receive();
      if (d == null) return;
      rx++;
      try {
        final m = jsonDecode(utf8.decode(d.data));
        if (m is Map<String, dynamic>) {
          m['source_ip'] = d.address.address;
          _ctl.add(m);
        }
      } catch (_) {}
    });
    return s;
  }

  /// Envoie une commande de mesure (GATT_CMD) a une gateway.
  void sendCommand(Map<String, dynamic> cmd) {
    final s = _send;
    if (s == null) return;
    s.send(utf8.encode(jsonEncode(cmd)), InternetAddress(cmdGroup), cmdPort);
  }

  Future<void> stop() async {
    _obs?.close();
    _res?.close();
    _send?.close();
    _obs = null;
    _res = null;
    _send = null;
    if (Platform.isAndroid) {
      try {
        await _channel.invokeMethod('release');
      } catch (_) {}
    }
  }
}
