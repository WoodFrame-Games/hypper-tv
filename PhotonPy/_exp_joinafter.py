#!/usr/bin/env python3
"""CreateRoom, затем JoinLobby на том же GS-соединении — проверим публикацию."""
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


async def main() -> int:
    name = "PyL" + time.strftime("%H%M%S")
    print("room:", name)
    st = pt.make_state("c")
    st["custom_id"] = ph.default_uid()
    st["nickname"] = "PyHost"
    if not await pt.connect_to_name_server(st):
        return 1

    payload = pt.build_gs_create_payload(name, pt.build_simple_hashtable(), 0, "PyHost")
    await st["master_ws"].send_operation(payload)

    gs = None
    for _ in range(12):
        mt, data = await st["master_ws"].receive_timeout(2000)
        if data is None:
            break
        if mt == 3 and data and data[0] == 0xE3:
            gs = pt.parse_simple_string(data, 230)
            print("master rc=", pt.read_short_le(data, 1), "gs=", gs)
            break
    if not gs:
        print("no gs"); return 2

    await st["master_ws"].aclose()
    st["master_ws"] = None
    if not await pt.connect_to_game_server(st, gs):
        return 3

    await st["master_ws"].send_operation(payload)
    for _ in range(6):
        mt, data = await st["master_ws"].receive_timeout(1200)
        if data is None:
            break
        if mt == 3 and data:
            print(f"gs op {data[0]} rc={pt.read_short_le(data, 1)}")
        elif mt == 4 and data:
            print(f"gs event {data[0]}")

    # JoinLobby уже внутри комнаты
    await st["master_ws"].send_operation(pt.build_op(229, (213, ""), (212, bytes([0]))))
    for _ in range(8):
        mt, data = await st["master_ws"].receive_timeout(1200)
        if data is None:
            break
        if mt == 3 and data:
            print(f"gs lobby op {data[0]} rc={pt.read_short_le(data, 1)}")
        elif mt == 4 and data:
            print(f"gs lobby event {data[0]}")

    print("lobby:", await asyncio.to_thread(lobby_has, name))
    await st["master_ws"].aclose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))