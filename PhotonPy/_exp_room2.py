#!/usr/bin/env python3
"""Создание комнаты из Python: полный payload как у игры, уникальное имя."""
import asyncio
import io
import sys
import time

import photon0509 as ph
import ptWorkFreeze as pt


def lobby_has(name: str) -> str:
    c = ph.PhotonUdp(uid=ph.default_uid())
    try:
        if not c.connect() or c.authenticate() != 0:
            return "auth fail"
        c.join_lobby()
        rooms = c.collect_rooms(8, 2.0)
        return "yes" if name in rooms else f"no ({len(rooms)})"
    finally:
        c.close()


async def make(name: str) -> None:
    st = pt.make_state("c")
    st["custom_id"] = ph.default_uid()
    st["nickname"] = "PyHost"
    if not await pt.connect_to_name_server(st):
        print("connect fail"); return

    payload = pt.build_gs_create_payload(name, pt.build_simple_hashtable(), 0, "PyHost")
    minimal = io.BytesIO()
    minimal.write(bytes([0xE3, 0x03]))
    minimal.write(b"\xff\x07")
    pt.write_varint(minimal, len(name))
    minimal.write(name.encode())
    minimal.write(b"\xf8")
    minimal.write(pt.build_simple_hashtable())
    minimal.write(bytes([0xF1, 0x1C]))
    await st["master_ws"].send_operation(minimal.getvalue())

    gs = None
    for _ in range(12):
        mt, data = await st["master_ws"].receive_timeout(2500)
        if data is None:
            break
        if mt == 3 and data and data[0] == 0xE3:
            rc = pt.read_short_le(data, 1)
            gs = pt.parse_simple_string(data, 230)
            print(f"master rc={rc} gs={gs}")
            break
    if not gs:
        print("no gs"); return

    await st["master_ws"].aclose()
    st["master_ws"] = None
    if not await pt.connect_to_game_server(st, gs):
        print("gs fail"); return

    await st["master_ws"].send_operation(payload)
    joined = False
    for _ in range(12):
        mt, data = await st["master_ws"].receive_timeout(1200)
        if data is None:
            print("gs closed")
            break
        if mt == 255:
            continue
        if mt == 4 and data:
            code = data[0]
            print(f"gs event {code} ({len(data)}b)")
            if code == 255:
                ev = pt.parse_event_data(data)
                print("JOIN event, actor =", ev.get("params", {}).get(254))
                joined = True
                break
        elif mt == 3 and data:
            print(f"gs op {data[0]} rc={pt.read_short_le(data, 1)}")

    print("joined:", joined)
    print("lobby:", await asyncio.to_thread(lobby_has, name))
    # держим комнату
    for _ in range(8):
        await asyncio.sleep(1)
        mt, data = await st["master_ws"].receive_timeout(300)
    await st["master_ws"].aclose()


async def main() -> int:
    name = "PyRoom" + time.strftime("%H%M%S")
    print("room:", name)
    await make(name)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))