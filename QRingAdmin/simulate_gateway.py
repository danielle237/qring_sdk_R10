"""
Simulateur d'un gateway Android (TV) pour tester l'admin sans vraie bague.
Il se comporte comme l'app QRing MQTT : statut chaque minute, réponse aux commandes.

    python simulate_gateway.py --name TV-Chambre-104 --mac C4:A1:5F:22:A4:F1
"""
import argparse, json, random, threading, time
import paho.mqtt.client as mqtt

ap = argparse.ArgumentParser()
ap.add_argument("--host", default="localhost"); ap.add_argument("--port", type=int, default=1883)
ap.add_argument("--user", default=""); ap.add_argument("--password", default="")
ap.add_argument("--prefix", default="eis/colmi"); ap.add_argument("--name", default="TV-Chambre-104")
ap.add_argument("--mac", default="C4:A1:5F:22:A4:F1"); ap.add_argument("--removed", action="store_true",
                help="simule une bague retirée (mesures → ring_removed)")
a = ap.parse_args()

state = {"mac": a.mac, "battery": random.randint(35, 95), "worn": None, "lang": "fr", "removed": a.removed}
tmac = lambda m: m.replace(":", "").upper()
gw_base = f"{a.prefix}/gateway/{a.name}"
ring_base = lambda: f"{a.prefix}/{tmac(state['mac'])}" if state["mac"] else gw_base

def status(online=True):
    return {"online": online, "ring": "connected" if state["mac"] else "no_ring", "ringMac": state["mac"] or "",
            "ringModel": "R06", "ringName": f"R06_{tmac(state['mac'] or '0000')[-4:]}", "firmware": "2.1.8",
            "battery": state["battery"], "charging": False, "worn": state["worn"], "measuring": None,
            "gateway": a.name, "deviceName": a.name.replace("-", " "), "lanIp": "192.168.1.%d" % random.randint(20, 99),
            "wanIp": "41.226.12.34", "lang": state["lang"], "appVersion": "1.0.0", "ts": int(time.time())}

def base(cmd, req):
    d = {"type": cmd, "source": "mqtt", "ringMac": state["mac"], "ringModel": "R06", "gateway": a.name, "ts": int(time.time())}
    if req: d["reqId"] = req
    return d

def pub(topic, obj, retain=False):
    c.publish(topic, json.dumps(obj), qos=1, retain=retain)

def publish_status():
    pub(f"{ring_base()}/status", status(), True)
    pub(f"{gw_base}/status", status(), True)

def measure(cmd, req):
    pub(f"{ring_base()}/{cmd}", {**base(cmd, req), "status": "measuring"})
    time.sleep(random.uniform(4, 9))
    if state["removed"]:
        state["worn"] = False
        pub(f"{ring_base()}/{cmd}", {**base(cmd, req), "status": "error", "error": "ring_removed"}); publish_status(); return
    state["worn"] = True
    v = {"hr": {"value": random.randint(62, 88), "rri": random.randint(700, 950), "unit": "bpm"},
         "spo2": {"value": random.randint(95, 99), "unit": "%"},
         "temp": {"value": round(random.uniform(36.2, 37.1), 1), "unit": "°C"},
         "bp": {"sbp": random.randint(110, 130), "dbp": random.randint(70, 85), "unit": "mmHg"},
         "hrv": {"value": random.randint(30, 70), "unit": "ms"},
         "stress": {"value": random.randint(15, 45), "unit": "score"},
         "all": {"hr": random.randint(62, 88), "spo2": random.randint(95, 99), "temp": round(random.uniform(36.2, 37.1), 1),
                 "sbp": random.randint(110, 130), "dbp": random.randint(70, 85), "hrv": random.randint(30, 70), "stress": random.randint(15, 45)},
         "steps": {"steps": random.randint(1500, 9000), "distance": random.randint(1000, 6000), "calories": random.randint(80, 400)},
         "battery": {"value": state["battery"], "charging": False, "unit": "%"}}.get(cmd, {})
    pub(f"{ring_base()}/{cmd}", {**base(cmd, req), "status": "ok", **v})

def on_message(cl, ud, msg):
    try: p = json.loads(msg.payload)
    except Exception: p = {"cmd": msg.payload.decode().strip()}
    cmd, req = p.get("cmd"), p.get("reqId")
    via_gw = msg.topic.startswith(gw_base)
    print("⬇", msg.topic, p)
    if cmd == "ping": publish_status()
    elif cmd == "lang":
        state["lang"] = p.get("value", "fr"); pub(f"{gw_base}/lang", {**base(cmd, req), "status": "ok", "lang": state["lang"]}); publish_status()
    elif cmd == "scan":
        time.sleep(2)
        pub(f"{gw_base}/scan", {**base(cmd, req), "status": "ok", "count": 2, "rings": [
            {"name": "R06_A4F1", "mac": "C4:A1:5F:22:A4:F1", "rssi": -58}, {"name": "R02_1B7C", "mac": "E2:09:3A:61:1B:7C", "rssi": -74}]})
    elif cmd == "unbind":
        old = state["mac"]; state["mac"] = None
        pub(f"{a.prefix}/{tmac(old)}/status", {**status(False), "ring": "unbound", "ringMac": old, "reason": "ring_unbound"}, True)
        pub(f"{gw_base}/unbind", {**base(cmd, req), "status": "ok", "ringMac": old}); resubscribe(); publish_status()
    elif cmd == "bind":
        pub(f"{gw_base}/bind", {**base(cmd, req), "status": "searching", "mac": p.get("mac")})
        time.sleep(3); state["mac"] = p.get("mac").upper(); resubscribe()
        pub(f"{gw_base}/bind", {**base(cmd, req), "status": "ok", "ringMac": state["mac"], "ringModel": "R06"}); publish_status()
    elif cmd in ("hr", "spo2", "temp", "bp", "hrv", "stress", "all", "steps", "battery"):
        if not state["mac"]:
            pub(f"{gw_base}/{cmd}", {**base(cmd, req), "status": "error", "error": "ring_disconnected"}); return
        threading.Thread(target=measure, args=(cmd, req), daemon=True).start()

def resubscribe():
    c.subscribe(f"{gw_base}/cmd", 1)
    if state["mac"]: c.subscribe(f"{ring_base()}/cmd", 1)

c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"sim-{a.name}")
if a.user: c.username_pw_set(a.user, a.password)
c.will_set(f"{ring_base()}/status", json.dumps(status(False)), 1, True)
c.on_message = on_message
c.on_connect = lambda cl, ud, fl, rc, pr=None: (resubscribe(), publish_status(), print("connecté", a.name))
c.connect(a.host, a.port, 30)
c.loop_start()
try:
    while True:
        time.sleep(60); publish_status()
except KeyboardInterrupt:
    pass
