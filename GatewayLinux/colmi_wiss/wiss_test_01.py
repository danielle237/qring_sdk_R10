#!/usr/bin/env python3
# WISS / COLMI SIMPLE - TEST 01

import asyncio
import subprocess
import time
from datetime import datetime
from pathlib import Path

from bleak import BleakClient
from bleak.exc import BleakDeviceNotFoundError

MAC = "30:32:42:32:64:01"
NAME = "COLMI R10_6401"

RX = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
TX = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"
HW = "00002A27-0000-1000-8000-00805F9B34FB"
FW = "00002A26-0000-1000-8000-00805F9B34FB"

CMD_BATTERY = 0x03
CMD_START = 0x69
CMD_STOP = 0x6A
HR = 0x01
SPO2 = 0x03

CONNECT_TIMEOUT = 15
MEASURE_TIMEOUT = 35
TARGET_SAMPLES = 6

Path("logs").mkdir(exist_ok=True)
LOGFILE = Path("logs") / f"wiss_test_01_{datetime.now():%Y%m%d_%H%M%S}.log"


def ts():
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def log(msg=""):
    line = f"{ts()} | {msg}"
    print(line, flush=True)
    with LOGFILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def hx(data):
    return " ".join(f"{b:02X}" for b in data)


def packet(command, data=b""):
    p = bytearray(16)
    p[0] = command
    p[1:1 + len(data)] = data
    p[15] = sum(p) & 0xFF
    return bytes(p)


BATTERY_PACKET = packet(CMD_BATTERY)


def start_packet(kind):
    return packet(CMD_START, bytes([kind, 0x01]))


def stop_packet(kind):
    return packet(CMD_STOP, bytes([kind, 0x00, 0x00]))


async def restart_bt(reason):
    log(f"BT RESTART | {reason}")
    p = await asyncio.create_subprocess_exec("systemctl", "restart", "bluetooth")
    await p.wait()
    log(f"BT RESTART | rc={p.returncode}")
    await asyncio.sleep(2)


async def disconnect(client, label):
    if client is None:
        return
    try:
        if client.is_connected:
            log(f"{label} | DISCONNECT START")
            await asyncio.wait_for(client.disconnect(), 10)
        log(f"{label} | CONNECTED={client.is_connected}")
    except Exception as e:
        log(f"{label} | DISCONNECT ERROR | {type(e).__name__}: {e}")


async def connect(label):
    log(f"{label} | CONNECT START | {MAC}")
    c = BleakClient(MAC)
    t0 = time.perf_counter()
    await asyncio.wait_for(c.connect(), CONNECT_TIMEOUT)
    log(f"{label} | CONNECT OK | {time.perf_counter()-t0:.3f}s")
    return c


async def info_battery():
    client = None
    result = None
    log("\n=== 1. INFO + BATTERY ===")

    try:
        client = await connect("INFO")

        hw = bytes(await client.read_gatt_char(HW)).decode(errors="replace").rstrip("\x00")
        fw = bytes(await client.read_gatt_char(FW)).decode(errors="replace").rstrip("\x00")
        log(f"INFO | HW={hw}")
        log(f"INFO | FW={fw}")

        done = asyncio.Event()
        battery = {"level": None, "charging": None}

        def notify(_sender, data):
            raw = bytes(data)
            log(f"INFO | RX RAW | {hx(raw)}")
            if len(raw) == 16 and raw[0] == CMD_BATTERY:
                battery["level"] = raw[1]
                battery["charging"] = bool(raw[2])
                done.set()

        await client.start_notify(TX, notify)
        log(f"INFO | TX BATTERY | {hx(BATTERY_PACKET)}")
        await client.write_gatt_char(RX, BATTERY_PACKET, response=False)

        try:
            await asyncio.wait_for(done.wait(), 5)
        except asyncio.TimeoutError:
            log("INFO | BATTERY TIMEOUT")

        log(f"INFO | BATTERY={battery['level']}% | CHARGING={battery['charging']}")
        result = {"hw": hw, "fw": fw, **battery}

    except (BleakDeviceNotFoundError, asyncio.TimeoutError) as e:
        log(f"INFO | NOT AVAILABLE | {type(e).__name__}: {e}")
        log("FR : La bague est-elle hors portée ou déchargée ?")
        log("EN : Is the ring out of range or discharged?")
    except Exception as e:
        log(f"INFO | ERROR | {type(e).__name__}: {e}")
        log("FR : La bague est-elle hors portée ou déchargée ?")
        log("EN : Is the ring out of range or discharged?")
    finally:
        await disconnect(client, "INFO")
        await restart_bt("fin INFO")

    return result


async def measure(kind, label):
    client = None
    samples = []
    error = None
    done = asyncio.Event()
    start_sent = False
    stop_sent = False

    log(f"\n=== {label} ===")

    def notify(_sender, data):
        nonlocal error
        raw = bytes(data)
        log(f"{label} | RX RAW | {hx(raw)}")

        if len(raw) != 16 or raw[0] != CMD_START or raw[1] != kind:
            return

        err = raw[2]
        value = raw[3]
        log(f"{label} | error={err} value={value}")

        if err != 0:
            error = err
            done.set()
        elif value != 0:
            samples.append(value)
            log(f"{label} | SAMPLE #{len(samples)} = {value}")
            if len(samples) >= TARGET_SAMPLES:
                done.set()

    try:
        client = await connect(label)
        await client.start_notify(TX, notify)
        await asyncio.sleep(0.5)

        p_start = start_packet(kind)
        log(f"{label} | TX START | {hx(p_start)}")
        t0 = time.perf_counter()
        await client.write_gatt_char(RX, p_start, response=False)
        start_sent = True

        try:
            await asyncio.wait_for(done.wait(), MEASURE_TIMEOUT)
        except asyncio.TimeoutError:
            log(f"{label} | TIMEOUT {MEASURE_TIMEOUT}s")

        p_stop = stop_packet(kind)
        log(f"{label} | TX STOP | {hx(p_stop)}")
        await client.write_gatt_char(RX, p_stop, response=False)
        stop_sent = True

        # Observer d'éventuels paquets tardifs après STOP.
        await asyncio.sleep(1)

        log(f"{label} | DURATION={time.perf_counter()-t0:.3f}s")
        log(f"{label} | SAMPLES={samples}")

        if not samples or error is not None:
            if kind == HR:
                log("FR : La bague est-elle portée ?")
                log("EN : Is the ring being worn?")
            else:
                log("FR : La bague est-elle portée au doigt ?")
                log("EN : Is the ring being worn on a finger?")

    except (BleakDeviceNotFoundError, asyncio.TimeoutError) as e:
        log(f"{label} | DEVICE NOT AVAILABLE | {type(e).__name__}: {e}")
        log("FR : La bague est-elle hors portée ou déchargée ?")
        log("EN : Is the ring out of range or discharged?")
    except Exception as e:
        log(f"{label} | ERROR | {type(e).__name__}: {e}")
    finally:
        # Une seule tentative de STOP de sécurité. Aucun retry.
        if client and client.is_connected and start_sent and not stop_sent:
            try:
                p_stop = stop_packet(kind)
                log(f"{label} | SAFETY TX STOP | {hx(p_stop)}")
                await client.write_gatt_char(RX, p_stop, response=False)
                await asyncio.sleep(0.5)
            except Exception as e:
                log(f"{label} | SAFETY STOP ERROR | {e}")

        await disconnect(client, label)
        await restart_bt(f"fin {label}")

    return {"samples": samples, "error": error, "ok": bool(samples) and error is None}


async def main():
    log("=" * 70)
    log("WISS / COLMI SIMPLE - TEST 01")
    log(f"TARGET : {NAME} | {MAC}")
    log(f"LOG    : {LOGFILE}")
    log("INFO -> reset BT -> HR -> reset BT -> SpO2 -> reset BT")
    log("=" * 70)

    info = await info_battery()
    if info is None:
        log("TEST END | INFO unavailable")
        return

    hr = await measure(HR, "HEART_RATE")
    spo2 = await measure(SPO2, "SPO2")

    log("\n=== RESULTAT FINAL / FINAL RESULT ===")
    log(f"HW       : {info['hw']}")
    log(f"FW       : {info['fw']}")
    log(f"BATTERY  : {info['level']}%")
    log(f"CHARGING : {info['charging']}")

    if hr["ok"] and spo2["ok"]:
        log(f"HR   : {hr['samples']}")
        log(f"SpO2 : {spo2['samples']}")
    else:
        log(f"HR   : {hr['samples']} | error={hr['error']}")
        log(f"SpO2 : {spo2['samples']} | error={spo2['error']}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nCtrl+C")
    finally:
        # Filet de sécurité final demandé pour WISS.
        subprocess.run(["systemctl", "restart", "bluetooth"], check=False)
