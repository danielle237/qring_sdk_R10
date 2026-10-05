#!/usr/bin/env python3
import asyncio, time
from datetime import datetime
from bleak import BleakClient
from bleak.exc import BleakDeviceNotFoundError

MAC="30:32:42:32:64:01"
RX="6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
TX="6E400003-B5A3-F393-E0A9-E50E24DCCA9E"
CMD_START=0x69
CMD_STOP=0x6A
TEMP_KIND=0x0F
CONNECT_TIMEOUT=15
CAPTURE_SECONDS=40

def ts(): return datetime.now().strftime("%H:%M:%S.%f")[:-3]
def hx(data): return " ".join(f"{b:02X}" for b in bytes(data))

def packet(command, data=b""):
    p=bytearray(16)
    p[0]=command
    p[1:1+len(data)]=data
    p[15]=sum(p)&0xFF
    return bytes(p)

def start_packet(kind): return packet(CMD_START, bytes([kind,0x01]))
def stop_packet(kind): return packet(CMD_STOP, bytes([kind,0x00,0x00]))

async def main():
    client=None
    rx_count=0
    matching_count=0
    t_start=None

    print("="*72)
    print("EIS / COLMI R10 - TEMPERATURE RAW HEX DIAGNOSTIC V1")
    print(f"TARGET: {MAC} | TYPE CANDIDAT: 0x{TEMP_KIND:02X} | CAPTURE: {CAPTURE_SECONDS}s")
    print("AUCUN DECODAGE: affichage des octets recus tels quels.")
    print("="*72)

    def notify(_sender,data):
        nonlocal rx_count, matching_count
        raw=bytes(data)
        rx_count+=1
        elapsed=time.perf_counter()-t_start if t_start is not None else 0
        marker=""
        if len(raw)>=2 and raw[0]==CMD_START and raw[1]==TEMP_KIND:
            matching_count+=1
            marker="  <=== 69 0F"
        print(f"{ts()} | RX #{rx_count:03d} | +{elapsed:7.3f}s | len={len(raw):2d} | {hx(raw)}{marker}",flush=True)

    try:
        print(f"{ts()} | CONNECT START")
        client=BleakClient(MAC)
        await asyncio.wait_for(client.connect(),CONNECT_TIMEOUT)
        print(f"{ts()} | CONNECT OK")
        await client.start_notify(TX,notify)
        await asyncio.sleep(.5)

        start=start_packet(TEMP_KIND)
        print(f"{ts()} | TX START | {hx(start)}")
        t_start=time.perf_counter()
        await client.write_gatt_char(RX,start,response=False)
        await asyncio.sleep(CAPTURE_SECONDS)

        stop=stop_packet(TEMP_KIND)
        print(f"{ts()} | TX STOP  | {hx(stop)}")
        await client.write_gatt_char(RX,stop,response=False)
        await asyncio.sleep(2)

        try: await client.stop_notify(TX)
        except Exception as e: print(f"{ts()} | STOP_NOTIFY WARNING | {e}")

        print("="*72)
        print(f"RX totaux: {rx_count}")
        print(f"RX 69 0F : {matching_count}")
        print("Ne pas convertir en degres a ce stade: garder la capture HEX brute.")
        print("="*72)
    except (BleakDeviceNotFoundError,asyncio.TimeoutError) as e:
        print(f"{ts()} | NOT AVAILABLE | {type(e).__name__}: {e}")
    except Exception as e:
        print(f"{ts()} | ERROR | {type(e).__name__}: {e}")
    finally:
        if client is not None:
            try:
                if client.is_connected:
                    print(f"{ts()} | DISCONNECT START")
                    await asyncio.wait_for(client.disconnect(),10)
                    print(f"{ts()} | DISCONNECT OK")
            except Exception as e:
                print(f"{ts()} | DISCONNECT WARNING | {e}")

if __name__=="__main__":
    asyncio.run(main())
