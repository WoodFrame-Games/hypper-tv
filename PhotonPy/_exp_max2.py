#!/usr/bin/env python3
"""Последняя проверка: MaxPlayers=2 вместо 200 в GameProperties."""
import asyncio
import io
import sys
import time

import photon0509 as ph
import ptWorkFreeze as pt


def ht_max2() -> bytes:
    buf = io.BytesIO()
    buf.write(b"\x15")
    pt.write_varint(buf, 10)
    pt.write_byte_entry(buf, 255, 2)          # MaxPlayers = 2
    pt.write_int_entry(buf, 243, 2)
    pt.write_bool_entry(buf, 254, True)
    pt.write_bool_entry(buf, 253, True)
    pt.write_string_array_entry(buf, 250, ["Map", "GameMode", "PvP", "Nextbot", "OnlyModUsers"])
    pt.write_string_prop(buf, "Map", "FlatGrass")
    pt.write_int_prop(buf, "GameMode", 0)
    pt.write_bool_prop(buf, "PvP", True)
    pt.write_bool_prop(buf, "Nextbot", False)
    pt.write_bool_prop(buf, "OnlyModUsers", False)
    return buf.getvalue()


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


async def main() -> int:
    name = "Py2P" + time.strftime("%H%M%S")
    print("room:", name)
    st = pt.make_state("c")
    st["custom_id"] = ph.default_uid()
    st["nickname"] = "PyHost"
    if not await pt.connect_to_name_server(st):
        return 1

    payload = pt.build_gs_create_payload(name, ht_max2(), 0, "PyHost")
    await st["master_ws"].send_operation(payload)
    gs = None
    for _ in range(12):
        mt, data = await st["master_ws"].receive_timeout(2000)
        if data is None:
            break
        if mt == 3 and data and data[0] == 0xE3:
            print("master rc=", pt.read_short_le(data, 1), "gs=", pt.parse_simple_string(data, 230))
            gs = pt.parse_simple_string(data, 230)
            break
    if not gs:
        return 2

    await st["master_ws"].aclose()
    st["master_ws"] = None
    if not await pt.connect_to_game_server(st, gs):
        return 3

    await st["master_ws"].send_operation(payload)
    for _ in range(8):
        mt, data = await st["master_ws"].receive_timeout(1200)
        if data is None:
            break
        if mt == 3 and data:
            print(f"gs op {data[0]} rc={pt.read_short_le(data, 1)}")
        elif mt == 4 and data:
            print(f"gs event {data[0]}")

    print("lobby:", await asyncio.to_thread(lobby_has, name))
    await st["master_ws"].aclose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))