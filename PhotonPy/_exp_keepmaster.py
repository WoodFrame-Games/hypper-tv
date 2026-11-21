#!/usr/bin/env python3
"""Вариант E: не закрывать соединение с мастером при переходе на GS."""
import asyncio
import io
import sys
import time

import photon0509 as ph
import ptWorkFreeze as pt
from photon0509 import AsyncPhotonUdp

from _exp_publish import build, lobby_has


async def main() -> int:
    name = "PvE" + time.strftime("%H%M%S")
    st = pt.make_state("v")
    st["custom_id"] = "81749450a38f467283f04447cf64d99a"
    st["nickname"] = "PyHost"
    if not await pt.connect_to_name_server(st):
        return 1

    master = st["master_ws"]
    payload = build(name, visible_params=True, lobby_props=False, flags=1)
    await master.send_operation(payload)

    gs_addr = None
    for _ in range(10):
        mt, data = await master.receive_timeout(2000)
        if data is None:
            break
        if mt == 3 and data and data[0] == 0xE3:
            gs_addr = pt.parse_simple_string(data, 230)
            print("master rc=", pt.read_short_le(data, 1), "gs=", gs_addr)
            break
    if not gs_addr:
        print("no gs")
        return 2

    host, port = gs_addr.split(":") if ":" in gs_addr else ("82.158.120.189", "27002")
    gs = AsyncPhotonUdp(host, int(port), uid="3edcc77ae6ba4d44a280edeb038b88e5")
    if not await gs.connect() or not await gs.send_operation(
            pt.build_op(230, (224, ph.APP_ID), (220, ph.APP_VER), (223, ph.CLIENT_VER),
                        (225, "3edcc77ae6ba4d44a280edeb038b88e5"), (217, bytes([0])),
                        (216, "s=" + ph.sign_for("3edcc77ae6ba4d44a280edeb038b88e5")))):
        print("gs auth send fail")
        return 3
    for _ in range(8):
        mt, data = await gs.receive_timeout(1200)
        if mt == 3 and data:
            print("gs auth op", data[0], "rc=", pt.read_short_le(data, 1))
            break

    await gs.send_operation(payload)
    for _ in range(6):
        mt, data = await gs.receive_timeout(1200)
        if data is None:
            break
        if mt == 3 and data:
            print("gs create op", data[0], "rc=", pt.read_short_le(data, 1))

    print("LOBBY:", await asyncio.to_thread(lobby_has, name), f"(room {name})")
    # мастер жив — вдруг комната появится позже
    for i in range(10):
        await asyncio.sleep(1)
        mt, data = await master.receive_timeout(400)
        if mt == 4 and data:
            print("master event", data[0])
    print("LOBBY(2):", await asyncio.to_thread(lobby_has, name))

    await gs.aclose()
    await master.aclose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))