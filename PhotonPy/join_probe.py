#!/usr/bin/env python3
"""join_probe.py — подключиться к существующей комнате и показать события."""
import argparse
import asyncio
import io
import sys
import time

import photon0509 as ph
import ptWorkFreeze as pt


async def join_room(st: dict, name: str) -> bool:
    buf = io.BytesIO()
    buf.write(bytes([0xE2, 0x01]))          # op 226 JoinGame, 1 param
    buf.write(b"\xff\x07")
    raw = name.encode()
    pt.write_varint(buf, len(raw))
    buf.write(raw)

    await st["master_ws"].send_operation(buf.getvalue())
    print(f"join '{name}'... ", end="", flush=True)

    gs_addr = None
    for _ in range(15):
        mt, data = await st["master_ws"].receive_timeout(2500)
        if data is None:
            break
        if mt == 255:
            continue
        if mt == 3 and data and data[0] == 0xE2:
            rc = pt.read_short_le(data, 1)
            if rc != 0:
                print(f"FAIL rc={rc} {pt.extract_debug_message(data)}")
                return False
            gs_addr = pt.parse_simple_string(data, 230)
            break
    if not gs_addr:
        print("FAIL (no gs address)")
        return False
    print(f"GS:{gs_addr}")

    await st["master_ws"].aclose()
    st["master_ws"] = None
    if not await pt.connect_to_game_server(st, gs_addr):
        return False

    await st["master_ws"].send_operation(buf.getvalue())
    for _ in range(15):
        mt, data = await st["master_ws"].receive_timeout(3000)
        if data is None:
            break
        if mt == 255:
            continue
        if mt == 2 and data and data[0] == 255:
            ev = pt.parse_event_data(data)
            print(f"in room (actor={ev.get('params', {}).get(254)})")
            return True
        if mt == 3 and data and data[0] == 0xE2:
            rc = pt.read_short_le(data, 1)
            if rc == 0:
                print("in room")
                return True
            print(f"FAIL join on GS rc={rc} {pt.extract_debug_message(data)}")
            return False
    print("FAIL (timeout)")
    return False


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--room", required=True)
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--uid", default=None)
    args = ap.parse_args()

    st = pt.make_state("probe")
    st["custom_id"] = args.uid or ph.default_uid()
    st["nickname"] = "PyProbe"
    if not await pt.connect_to_name_server(st):
        return 1
    if not await join_room(st, args.room):
        return 2

    t_end = time.time() + args.seconds
    while time.time() < t_end:
        mt, data = await st["master_ws"].receive_timeout(700)
        if data is None:
            print("closed")
            break
        if mt == 255:
            continue
        if mt == 5:
            print("disconnect:", pt.extract_debug_message_at(data, 2))
            break
        if mt == 4 and data:
            ev = data[0]
            if ev == 200:
                rpc = pt.parse_rpc_info(pt.parse_event_data(data))
                print(f"RPC {rpc.get('method')} view={rpc.get('view_id')}")
            elif ev in (202, 255, 254):
                print(f"event {ev}: {len(data)} bytes")
            elif ev == 226:
                print("PlayerEntered")
            else:
                print(f"event {ev} ({len(data)} b)")
        elif mt == 3 and data:
            print(f"op {data[0]} rc={pt.read_short_le(data,1) if len(data)>=3 else '?'}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))