#!/usr/bin/env python3
"""Комната из Python + второй клиент входит по имени (проверка работоспособности)."""
import asyncio
import io
import sys
import time

import photon0509 as ph
import ptWorkFreeze as pt

NAME = "PySelf" + time.strftime("%H%M%S")


async def create_host() -> dict:
    st = pt.make_state("host")
    st["custom_id"] = ph.default_uid()
    st["nickname"] = "PyHost"
    if not await pt.connect_to_name_server(st):
        return {}
    payload = pt.build_gs_create_payload(NAME, pt.build_simple_hashtable(), 0, "PyHost")
    await st["master_ws"].send_operation(payload)
    gs = None
    for _ in range(12):
        mt, data = await st["master_ws"].receive_timeout(2000)
        if data is None:
            break
        if mt == 3 and data and data[0] == 0xE3:
            gs = pt.parse_simple_string(data, 230)
            break
    if not gs:
        return {}
    await st["master_ws"].aclose()
    st["master_ws"] = None
    if not await pt.connect_to_game_server(st, gs):
        return {}
    await st["master_ws"].send_operation(payload)
    for _ in range(6):
        mt, data = await st["master_ws"].receive_timeout(1200)
        if data is None:
            break
    print("host: created", NAME)
    return st


async def join(name: str) -> bool:
    st = pt.make_state("guest")
    st["custom_id"] = ph.default_uid()
    st["nickname"] = "PyGuest"
    if not await pt.connect_to_name_server(st):
        return False
    req = io.BytesIO()
    req.write(bytes([0xE2, 0x01]))
    req.write(b"\xff\x07")
    pt.write_varint(req, len(name))
    req.write(name.encode())
    payload = req.getvalue()
    await st["master_ws"].send_operation(payload)
    gs = None
    for _ in range(12):
        mt, data = await st["master_ws"].receive_timeout(2000)
        if data is None:
            break
        if mt == 3 and data and data[0] == 0xE2:
            rc = pt.read_short_le(data, 1)
            gs = pt.parse_simple_string(data, 230)
            print("guest: join rc=", rc, "gs=", gs)
            break
    if not gs:
        return False
    await st["master_ws"].aclose()
    st["master_ws"] = None
    if not await pt.connect_to_game_server(st, gs):
        return False
    await st["master_ws"].send_operation(payload)
    for _ in range(8):
        mt, data = await st["master_ws"].receive_timeout(1200)
        if data is None:
            break
        if mt == 3 and data:
            print(f"guest: op {data[0]} rc={pt.read_short_le(data, 1)}")
        elif mt == 4 and data:
            print(f"guest: event {data[0]}")
    await st["master_ws"].aclose()
    return True


async def main() -> int:
    host = await create_host()
    if not host:
        print("host failed")
        return 1
    ok = await join(NAME)
    # хост тем временем должен получить PlayerEntered
    for _ in range(6):
        mt, data = await host["master_ws"].receive_timeout(800)
        if mt == 4 and data:
            print(f"host: event {data[0]}")
    await host["master_ws"].aclose()
    print("joined:", ok)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))