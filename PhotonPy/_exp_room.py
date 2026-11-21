#!/usr/bin/env python3
"""Комната из Python: проверяем существование (join по имени), видимость в лобби
и влияние флагов RoomOptions (191)."""
import asyncio
import io
import sys

import photon0509 as ph
import ptWorkFreeze as pt

NAME = "PYROOM"


def build_create(name: str, ht: bytes, flags=None) -> bytes:
    buf = io.BytesIO()
    n_params = 4 if flags is not None else 3
    buf.write(bytes([0xE3, n_params]))
    buf.write(b"\xff\x07")
    pt.write_varint(buf, len(name))
    buf.write(name.encode())
    buf.write(b"\xfa\x1c")          # 250 Broadcast = true
    buf.write(b"\xf8")
    buf.write(ht)                    # 248 GameProperties
    if flags is not None:
        buf.write(bytes([0xBF, 0x0B, flags & 0xFF]))   # 191 RoomOptions
    return buf.getvalue()


async def make(flags=None) -> None:
    name = NAME + time.strftime("%H%M%S")
    st = pt.make_state("c")
    st["custom_id"] = ph.default_uid()
    st["nickname"] = "PyHost"
    if not await pt.connect_to_name_server(st):
        print("connect fail"); return
    ht = pt.build_simple_hashtable()
    full = pt.build_gs_create_payload(NAME, ht, 0, "PyHost")
    payload = full          # одинаковый payload и мастеру, и игровому серверу
    _ = build_create(NAME, ht, flags)

    await st["master_ws"].send_operation(payload)
    gs = None
    for _ in range(12):
        mt, data = await st["master_ws"].receive_timeout(2500)
        if data is None:
            break
        if mt == 3 and data and data[0] == 0xE3:
            gs = pt.parse_simple_string(data, 230)
            print("master rc=", pt.read_short_le(data, 1), "gs=", gs)
            break
    if not gs:
        print("no gs"); return

    await st["master_ws"].aclose()
    st["master_ws"] = None
    if not await pt.connect_to_game_server(st, gs):
        print("gs connect fail"); return

    await st["master_ws"].send_operation(payload)
    joined = False
    for _ in range(10):
        mt, data = await st["master_ws"].receive_timeout(3000)
        if data is None:
            break
        if mt == 2 and data and data[0] == 255:
            print("join event -> in room")
            joined = True
            break
        if mt == 3 and data and data[0] == 0xE3:
            print("gs rc=", pt.read_short_le(data, 1))
    if not joined:
        print("no join event")
        # добираем вход явным JoinGame по имени
        jb = io.BytesIO()
        jb.write(bytes([0xE2, 0x01]))
        jb.write(b"\xff\x07")
        pt.write_varint(jb, len(NAME))
        jb.write(NAME.encode())
        await st["master_ws"].send_operation(jb.getvalue())
        for _ in range(8):
            mt, data = await st["master_ws"].receive_timeout(2000)
            if data is None:
                break
            if mt == 2 and data and data[0] == 255:
                print("join event after JoinGame")
                joined = True
                break
            if mt == 3 and data and data[0] == 0xE2:
                print("join rc=", pt.read_short_le(data, 1))
                if pt.read_short_le(data, 1) == 0:
                    joined = True
                break

    print("lobby:", await asyncio.to_thread(lobby_check))
    print("join by name:", await asyncio.to_thread(join_check))
    await st["master_ws"].aclose()


def lobby_check() -> str:
    c = ph.PhotonUdp(uid=ph.default_uid())
    try:
        if not c.connect() or c.authenticate() != 0:
            return "auth fail"
        c.join_lobby()
        rooms = c.collect_rooms(6, 1.5)
        return "yes" if NAME in rooms else f"no ({len(rooms)})"
    finally:
        c.close()


def join_check() -> str:
    c = ph.PhotonUdp(uid=ph.default_uid())
    try:
        if not c.connect() or c.authenticate() != 0:
            return "auth fail"
        c.send_op(ph.op_payload(226, [(255, NAME)]))
        for _ in range(10):
            for mt, data in c.pump(1.5):
                if mt == 3 and data and data[0] == 226:
                    return f"rc={pt.read_short_le(data, 1)}"
        return "no response"
    finally:
        c.close()


async def main() -> int:
    for flags in (None, 0, 0xFF):
        print(f"=== flags={flags} ===")
        await make(flags)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))