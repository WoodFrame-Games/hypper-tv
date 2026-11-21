#!/usr/bin/env python3
"""Проверка: комната, созданная Python-клиентом — видна ли в лобби и можно ли в неё войти."""
import asyncio
import io
import sys
import time

import photon0509 as ph
import ptWorkFreeze as pt

NAME = "PYTEST2P"


async def create(st: dict, name: str) -> bool:
    req = io.BytesIO()
    req.write(bytes([0xE3, 0x03]))
    req.write(b"\xff\x07")
    pt.write_varint(req, len(name))
    req.write(name.encode())
    req.write(b"\xf8")
    req.write(pt.build_simple_hashtable())
    req.write(bytes([0xF1, 0x1C]))
    payload = req.getvalue()

    await st["master_ws"].send_operation(payload)
    gs = None
    for _ in range(15):
        mt, data = await st["master_ws"].receive_timeout(2500)
        if data is None:
            return False
        if mt == 3 and data and data[0] == 0xE3:
            gs = pt.parse_simple_string(data, 230)
            break
    if not gs:
        print("no gs")
        return False
    print("gs:", gs)
    await st["master_ws"].aclose()
    st["master_ws"] = None
    if not await pt.connect_to_game_server(st, gs):
        return False
    await st["master_ws"].send_operation(payload)
    for _ in range(12):
        mt, data = await st["master_ws"].receive_timeout(3000)
        if data is None:
            return False
        if mt == 2 and data and data[0] == 255:
            print("created, in room")
            return True
        if mt == 3 and data and data[0] == 0xE3:
            rc = pt.read_short_le(data, 1)
            print("create rc:", rc)
            if rc != 0:
                return False
            continue
    return False


def lobby_check() -> str:
    c = ph.PhotonUdp(uid=ph.default_uid())
    try:
        if not c.connect() or c.authenticate() != 0:
            return "connect/auth fail"
        c.join_lobby()
        rooms = c.collect_rooms(8, 2.0)
        return f"yes" if NAME in rooms else f"no ({len(rooms)} rooms)"
    finally:
        c.close()


async def main() -> int:
    st = pt.make_state("creator")
    st["custom_id"] = ph.default_uid()
    st["nickname"] = "PyHost"
    if not await pt.connect_to_name_server(st):
        return 1
    if not await create(st, NAME):
        return 2
    for delay in (1, 5, 10):
        await asyncio.sleep(delay)
        print(f"lobby after +{delay}s:", await asyncio.to_thread(lobby_check))
    # держим комнату живой
    print("holding room 20s (Ctrl+C to stop)")
    for _ in range(20):
        mt, data = await st["master_ws"].receive_timeout(1000)
        if data is None:
            break
    await st["master_ws"].aclose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))