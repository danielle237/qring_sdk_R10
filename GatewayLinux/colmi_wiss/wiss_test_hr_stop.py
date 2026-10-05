#!/usr/bin/env python3
import asyncio, subprocess, time
from datetime import datetime
from pathlib import Path
from bleak import BleakClient
from bleak.exc import BleakDeviceNotFoundError

MAC="30:32:42:32:64:01"; NAME="COLMI R10_6401"
RX="6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
TX="6E400003-B5A3-F393-E0A9-E50E24DCCA9E"
CMD_START=0x69; CMD_STOP=0x6A; HR=0x01
CONNECT_TIMEOUT=15; MEASURE_TIMEOUT=35; TARGET_SAMPLES=6; PRESTOP_WAIT=3
LOGFILE=Path(__file__).resolve().parent / f"wiss_test_hr_stop_{datetime.now():%Y%m%d_%H%M%S}.log"

def log(s=""):
    line=f"{datetime.now().strftime('%H:%M:%S.%f')[:-3]} | {s}"
    print(line,flush=True)
    with LOGFILE.open("a",encoding="utf-8") as f:f.write(line+"\n")
def raw(s):
    with LOGFILE.open("a",encoding="utf-8") as f:f.write(f"{datetime.now().strftime('%H:%M:%S.%f')[:-3]} | {s}\n")
def hx(d): return " ".join(f"{b:02X}" for b in d)
def packet(cmd,data=b""):
    p=bytearray(16); p[0]=cmd; p[1:1+len(data)]=data; p[15]=sum(p)&0xFF; return bytes(p)
def start_packet(): return packet(CMD_START,bytes([HR,0x01]))
def stop_packet(): return packet(CMD_STOP,bytes([HR,0x00,0x00]))

async def main():
    samples=[]; state={"error":None,"start":None}; done=asyncio.Event(); client=None
    log("="*65); log("WISS - HR ONLY / PRE-STOP BEFORE START"); log(f"TARGET : {NAME} | {MAC}")
    log("CONNECT -> STOP HR -> WAIT 3s -> START HR -> STOP -> DISCONNECT"); log("="*65)
    def notify(_sender,data):
        b=bytes(data); raw(f"RX RAW | {hx(b)}")
        if len(b)!=16 or b[0]!=CMD_START or b[1]!=HR:return
        err,val=b[2],b[3]; raw(f"DECODE | error={err} value={val}")
        if err:
            state["error"]=err; log(f"HEART_RATE | MEASUREMENT ERROR | code={err}"); done.set(); return
        if val:
            if not samples: log(f"HEART_RATE | FIRST VALUE after {time.perf_counter()-state['start']:.3f} s")
            samples.append(val); log(f"HEART_RATE | SAMPLE #{len(samples)} = {val}")
            if len(samples)>=TARGET_SAMPLES:done.set()
    try:
        log("HEART_RATE | CONNECT START"); client=BleakClient(MAC); t=time.perf_counter()
        await asyncio.wait_for(client.connect(),CONNECT_TIMEOUT)
        log(f"HEART_RATE | CONNECT OK | {time.perf_counter()-t:.3f}s")
        await client.start_notify(TX,notify); await asyncio.sleep(.5)
        p=stop_packet(); raw(f"TX PRE-STOP | {hx(p)}"); log("HEART_RATE | PRE-STOP")
        await client.write_gatt_char(RX,p,response=False); log("HEART_RATE | PRE-STOP SENT")
        log("HEART_RATE | WAIT 3s"); await asyncio.sleep(PRESTOP_WAIT)
        p=start_packet(); raw(f"TX START | {hx(p)}"); log("HEART_RATE | START")
        state["start"]=time.perf_counter(); await client.write_gatt_char(RX,p,response=False)
        try: await asyncio.wait_for(done.wait(),MEASURE_TIMEOUT)
        except asyncio.TimeoutError: log(f"HEART_RATE | TIMEOUT {MEASURE_TIMEOUT}s")
        p=stop_packet(); raw(f"TX FINAL STOP | {hx(p)}")
        await client.write_gatt_char(RX,p,response=False); log("HEART_RATE | FINAL STOP SENT"); await asyncio.sleep(1)
    except (BleakDeviceNotFoundError,asyncio.TimeoutError) as e:
        log(f"HEART_RATE | NOT AVAILABLE | {type(e).__name__}: {e}")
    except Exception as e: log(f"HEART_RATE | ERROR | {type(e).__name__}: {e}")
    finally:
        if client and client.is_connected:
            log("HEART_RATE | DISCONNECT START")
            try: await asyncio.wait_for(client.disconnect(),10)
            except Exception as e: log(f"DISCONNECT ERROR | {e}")
        log(f"HEART_RATE | CONNECTED={client.is_connected if client else False}")
    log(""); log("=== RESULTAT ==="); log(f"HR : {samples}" + (f" | error={state['error']}" if state["error"] is not None else ""))
    log(f"LOG FILE : {LOGFILE}")

if __name__=="__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: print("\nCtrl+C")
    finally: subprocess.run(["systemctl","restart","bluetooth"],check=False)
