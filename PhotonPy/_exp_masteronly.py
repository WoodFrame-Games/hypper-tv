#!/usr/bin/env python3
"""CreateGame только мастеру: остаёмся на нём и смотрим, что придёт."""
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
    name = "PyM" + time.strftime("%H%M%S")
    print("room:", name)
    st = pt.make_state("c")
    st["custom_id"] = ph.default_uid()
    st["nickname"] = "PyHost"
    if not await pt.connect_to_name_server(st):
        return 1

    payload = pt.build_gs_create_payload(name, pt.build_simple_hashtable(), 0, "PyHost")
    await st["master_ws"].send_operation(payload)

    for i in range(14):
        mt, data = await st["master_ws"].receive_timeout(1500)
        if data is None:
            print("closed"); break
        if mt == 255:
            continue
        if mt == 3 and data:
            print(f"op {data[0]} rc={pt.read_short_le(data, 1)}")
        elif mt == 4 and data:
            print(f"event {data[0]}")
    print("lobby:", await asyncio.to_thread(lobby_has, name))
    await st["master_ws"].aclose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))