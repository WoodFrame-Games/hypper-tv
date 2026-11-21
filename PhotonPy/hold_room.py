#!/usr/bin/env python3
"""hold_room.py — создаёт комнату из Python и держит её активной.

Печатает статус, отвечает на события, шлёт keep-alive. Комната остаётся
живой, пока процесс работает (Ctrl+C — выйти).
"""
import argparse
import asyncio
import io
import sys
import time

import photon0509 as ph
import ptWorkFreeze as pt


async def create(st: dict, name: str, max_players: int) -> bool:
    ht = pt.build_simple_hashtable(2)
    payload = pt.build_gs_create_payload(name, ht, 0, st.get("nickname", "PyHost"))
    await st["master_ws"].send_operation(payload)

    gs = None
    for _ in range(15):
        mt, data = await st["master_ws"].receive_timeout(2500)
        if data is None:
            break
        if mt == 255:
            continue
        if mt == 3 and data and data[0] == 0xE3:
            rc = pt.read_short_le(data, 1)
            if rc != 0:
                print(f"master rc={rc} {pt.extract_debug_message(data)}")
                return False
            gs = pt.parse_simple_string(data, 230)
            st["gs_token"] = pt.parse_simple_string(data, 221)
            break
        if mt == 3 and data:
            print(f"master op {data[0]} rc={pt.read_short_le(data, 1)}")
        elif mt == 4 and data:
            pass
    if not gs:
        print("master: no game server address")
        return False
    print("gs:", gs, flush=True)

    await st["master_ws"].aclose()
    st["master_ws"] = None
    if not await pt.connect_to_game_server(st, gs):
        print("gs connect failed")
        return False

    await st["master_ws"].send_operation(payload)
    for _ in range(10):
        mt, data = await st["master_ws"].receive_timeout(1500)
        if data is None:
            break
        if mt == 3 and data and data[0] == 0xE3:
            rc = pt.read_short_le(data, 1)
            print(f"create rc={rc}", flush=True)
            return rc == 0
        if mt == 4 and data == b"\xff":
            return True
    return True


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--room", default="PyTest")
    ap.add_argument("--uid", default=None)
    args = ap.parse_args()

    st = pt.make_state("holder")
    st["custom_id"] = args.uid or ph.default_uid()
    st["nickname"] = "PyHost"
    st["running"] = True

    if not await pt.connect_to_name_server(st):
        print("connect/auth failed")
        return 1
    print("auth OK, uid =", st["custom_id"])

    for attempt in (1, 2, 3):
        if await create(st, args.room, 2):
            break
        print(f"create attempt {attempt} failed, retry in 10s")
        await asyncio.sleep(10)
        if not await pt.connect_to_name_server(st):
            return 1
    else:
        print("could not create room")
        return 2

    print(f"ROOM '{args.room}' ACTIVE (pid={__import__('os').getpid()})", flush=True)

    last_ping = time.time()
    last_status = time.time()
    players = 0
    while True:
        mt, data = await st["master_ws"].receive_timeout(1000)
        now = time.time()
        if now - last_ping > 3.0:
            try:
                await st["master_ws"].send_ping()
            except Exception:
                pass
            last_ping = now
        if now - last_status > 60.0:
            print(f"[{time.strftime('%H:%M:%S')}] still holding '{args.room}' "
                  f"(peer=0x{st['master_ws'].peer_id:04x})", flush=True)
            last_status = now
        if data is None:
            print("connection closed, reconnecting…", flush=True)
            await asyncio.sleep(2)
            if not await pt.connect_to_name_server(st):
                await asyncio.sleep(10)
                continue
            if not await create(st, args.room, 2):
                await asyncio.sleep(10)
                continue
            print(f"ROOM '{args.room}' RE-CREATED", flush=True)
            last_ping = time.time()
            continue
        if mt == 5:
            print("disconnect:", pt.extract_debug_message_at(data, 2), "-> reconnect", flush=True)
            await asyncio.sleep(2)
            if not await pt.connect_to_name_server(st):
                await asyncio.sleep(10)
                continue
            if not await create(st, args.room, 2):
                await asyncio.sleep(10)
                continue
            last_ping = time.time()
            continue
        if mt == 4 and data:
            ev = data[0]
            if ev == 226:
                players += 1
                print(f"[{time.strftime('%H:%M:%S')}] player entered (total ~{players})", flush=True)
            elif ev == 255:
                try:
                    info = pt.parse_event_data(data)
                    print(f"[{time.strftime('%H:%M:%S')}] join event: {info.get('params', {}).get(254)}", flush=True)
                except Exception:
                    print("join event")
            elif ev == 200:
                info = pt.parse_rpc_info(pt.parse_event_data(data))
                if info.get("method"):
                    print(f"[{time.strftime('%H:%M:%S')}] rpc {info.get('method')} view={info.get('view_id')}", flush=True)
            elif ev not in (229, 254, 202):
                print(f"[{time.strftime('%H:%M:%S')}] event {ev}", flush=True)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))