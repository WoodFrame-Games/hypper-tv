#!/usr/bin/env python3
"""CreateRoom с полным набором параметров Photon (как RoomOptionsToOpParameters)."""
import asyncio
import io
import sys
import time

import photon0509 as ph
import ptWorkFreeze as pt


def build_full(name: str, ht: bytes) -> bytes:
    b = io.BytesIO()
    params = [
        (0xFF, "str", name),        # 255 RoomName
        (0xFA, "bool", True),       # 250 Broadcast
        (0xF8, "raw", ht),          # 248 GameProperties
        (0xF1, "bool", False),      # 241 CleanupCacheOnLeave
        (0xE8, "bool", True),       # 232 CheckUserOnJoin
        (0xEB, "bool", False),      # 235
        (0xEC, "bool", False),      # 236
        (0xED, "int", 0),           # 237
        (0xCC, "int", 0),           # 204
        (0xEF, "bool", False),      # 239
        (0xBF, "byte", 0),          # 191 RoomOptions flags
        (0xFE, "bool", True),       # 254 IsVisible
        (0xFD, "bool", True),       # 253 IsOpen
        (0xF3, "int", 0),           # 243 EmptyRoomTTL
        (0xFB, "int", 0),           # 251 PlayerTTL
        (0xF9, "arr", ["Map", "GameMode", "PvP", "Nextbot", "PublicMechanism"]),  # 249 LobbyProperties
    ]
    b.write(bytes([0xE3, len(params)]))
    for code, kind, val in params:
        b.write(bytes([code]))
        if kind == "str":
            raw = val.encode()
            b.write(b"\x07")
            pt.write_varint(b, len(raw))
            b.write(raw)
        elif kind == "bool":
            b.write(b"\x1c" if val else b"\x1b")
        elif kind == "int":
            b.write(b"\x0b")
            b.write(bytes([val & 0xFF]))
        elif kind == "byte":
            b.write(b"\x0b")
            b.write(bytes([val & 0xFF]))
        elif kind == "raw":
            b.write(val)
        elif kind == "arr":
            b.write(b"\x47")
            pt.write_varint(b, len(val))
            for s in val:
                raw = s.encode()
                pt.write_varint(b, len(raw))
                b.write(raw)
    return b.getvalue()


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
    name = "PyF" + time.strftime("%H%M%S")
    print("room:", name)
    st = pt.make_state("c")
    st["custom_id"] = ph.default_uid()
    st["nickname"] = "PyHost"
    if not await pt.connect_to_name_server(st):
        return 1

    payload = build_full(name, pt.build_simple_hashtable())
    await st["master_ws"].send_operation(payload)

    gs = None
    for _ in range(12):
        mt, data = await st["master_ws"].receive_timeout(2000)
        if data is None:
            break
        if mt == 3 and data and data[0] == 0xE3:
            rc = pt.read_short_le(data, 1)
            gs = pt.parse_simple_string(data, 230)
            print(f"master rc={rc} gs={gs}")
            break
    if not gs:
        print("no gs"); return 2

    await st["master_ws"].aclose()
    st["master_ws"] = None
    if not await pt.connect_to_game_server(st, gs):
        return 3

    await st["master_ws"].send_operation(payload)
    for _ in range(10):
        mt, data = await st["master_ws"].receive_timeout(1500)
        if data is None:
            break
        if mt == 3 and data:
            print(f"gs op {data[0]} rc={pt.read_short_le(data, 1)}")
        elif mt == 4 and data:
            print(f"gs event {data[0]}")

    print("lobby:", await asyncio.to_thread(lobby_has, name))
    for _ in range(6):
        await asyncio.sleep(1)
    await st["master_ws"].aclose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))