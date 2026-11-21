#!/usr/bin/env python3
"""Проверка: публикуется ли комната, если на GS сначала войти в лобби."""
import asyncio
import io
import sys

import photon0509 as ph
import ptWorkFreeze as pt


def check_lobby(name: str) -> str:
    c = ph.PhotonUdp(uid=ph.default_uid())
    try:
        if not c.connect():
            return "connect-fail"
        if c.authenticate() != 0:
            return "auth-fail"
        c.join_lobby()
        rooms = c.collect_rooms(6, 1.5)
        return "yes" if name in rooms else f"no ({len(rooms)})"
    finally:
        c.close()


async def main() -> int:
    name = "PYMONGS"
    st = pt.make_state("exp")
    st["custom_id"] = ph.default_uid()
    st["nickname"] = "PyMon"
    if not await pt.connect_to_name_server(st):
        return 1

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
    gs_addr = None
    for _ in range(15):
        mt, data = await st["master_ws"].receive_timeout(2500)
        if data is None:
            break
        if mt == 3 and data and data[0] == 0xE3:
            gs_addr = pt.parse_simple_string(data, 230)
            break
    if not gs_addr:
        print("no gs"); return 2
    print("gs:", gs_addr)

    await st["master_ws"].aclose()
    st["master_ws"] = None
    if not await pt.connect_to_game_server(st, gs_addr):
        return 3

    # КЛЮЧЕВОЕ: сначала JoinLobby на GS
    await st["master_ws"].send_operation(pt.build_op(229, (213, ""), (212, bytes([0]))))
    for _ in range(6):
        mt, data = await st["master_ws"].receive_timeout(1500)
        if mt == 3 and data and data[0] == 0xE5:
            print("lobby on GS rc=", pt.read_short_le(data, 1))
            break

    await st["master_ws"].send_operation(payload)
    for _ in range(10):
        mt, data = await st["master_ws"].receive_timeout(3000)
        if data is None:
            break
        if mt == 2 and data and data[0] == 255:
            print("in room")
            break
        if mt == 3 and data and data[0] == 0xE3:
            print("create rc=", pt.read_short_le(data, 1))
            break

    print("lobby sees:", await asyncio.to_thread(check_lobby, name))
    await st["master_ws"].aclose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))