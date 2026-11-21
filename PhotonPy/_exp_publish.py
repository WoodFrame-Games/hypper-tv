#!/usr/bin/env python3
"""Подбор параметров CreateGame, при которых комната видна в лобби."""
import asyncio
import io
import sys
import time

import photon0509 as ph
import ptWorkFreeze as pt


def game_props(max_players: int = 2) -> bytes:
    buf = io.BytesIO()
    buf.write(b"\x15")
    pt.write_varint(buf, 17)
    pt.write_byte_entry(buf, 255, max_players)
    pt.write_int_entry(buf, 243, max_players)
    pt.write_bool_entry(buf, 254, True)
    pt.write_bool_entry(buf, 253, True)
    pt.write_string_array_entry(buf, 250, ["Map", "GameMode", "PvP", "Nextbot", "PublicMechanism"])
    pt.write_string_prop(buf, "Map", "FlatGrass")
    pt.write_int_prop(buf, "GameMode", 0)
    pt.write_string_prop(buf, "Password", "")
    pt.write_int_prop(buf, "MaxProps", 99999999)
    pt.write_int_prop(buf, "PropsCount", 0)
    pt.write_int_prop(buf, "MaxVehicles", 999999)
    pt.write_int_prop(buf, "VehiclesCount", 0)
    pt.write_bool_prop(buf, "PvP", True)
    pt.write_bool_prop(buf, "RPG", False)
    pt.write_bool_prop(buf, "PublicMechanism", True)
    pt.write_bool_prop(buf, "Nextbot", False)
    pt.write_bool_prop(buf, "OnlyModUsers", False)
    return buf.getvalue()


def build(name: str, *, visible_params: bool, lobby_props: bool, flags: int,
          nickname: str = "PyHost", max_players: int = 2) -> bytes:
    ht = game_props(max_players)
    head = [
        (0xFF, "str", name),
        (0xFA, "bool", True),
        (0xF8, "raw", ht),
        (0xF1, "bool", False),
        (0xE8, "bool", True),
        (0xBF, "byte", flags),
    ]
    if visible_params:
        head += [(0xFE, "bool", True), (0xFD, "bool", True)]
    if lobby_props:
        head += [(0xF9, "arr", ["Map", "GameMode", "PvP", "Nextbot", "PublicMechanism"])]
    if nickname:
        pp = io.BytesIO()
        pt.write_hashtable_raw(pp, [(bytes([255]), nickname), ("NickName", nickname)])
        head += [(0xF9 if False else 0xF9, None, None)] if False else []
    b = io.BytesIO()
    # PlayerProperties передаём отдельным кодом 249 только если не занят lobby_props
    entries = list(head)
    if nickname and not lobby_props:
        entries.append((0xF9, "pp", nickname))
    b.write(bytes([0xE3, len(entries)]))
    for code, kind, val in entries:
        b.write(bytes([code]))
        if kind == "str":
            raw = val.encode()
            b.write(b"\x07")
            pt.write_varint(b, len(raw))
            b.write(raw)
        elif kind == "bool":
            b.write(b"\x1c" if val else b"\x1b")
        elif kind == "byte":
            b.write(b"\x0b")
            b.write(bytes([val & 0xFF]))
        elif kind == "raw":
            b.write(val)
        elif kind == "arr":
            b.write(b"\x47")
            pt.write_varint(b, len(val))
            for s in val:
                r = s.encode()
                pt.write_varint(b, len(r))
                b.write(r)
        elif kind == "pp":
            h = io.BytesIO()
            pt.write_hashtable_raw(h, [(bytes([255]), val), ("NickName", val)])
            b.write(h.getvalue())
    return b.getvalue()


def lobby_has(name: str) -> str:
    c = ph.PhotonUdp(uid="662c82613a01451a86960a3d03e58acd")
    try:
        if not c.connect() or c.authenticate() != 0:
            return "auth fail"
        c.join_lobby()
        rooms = c.collect_rooms(7, 1.8)
        return "YES" if name in rooms else f"no({len(rooms)})"
    finally:
        c.close()


async def try_variant(label: str, **kw) -> bool:
    name = "Pv" + label + time.strftime("%H%M%S")
    st = pt.make_state("v")
    st["custom_id"] = "81749450a38f467283f04447cf64d99a"
    st["nickname"] = "PyHost"
    if not await pt.connect_to_name_server(st):
        print(f"{label}: connect fail"); return False
    payload = build(name, **kw)
    await st["master_ws"].send_operation(payload)

    gs = None
    for _ in range(10):
        mt, data = await st["master_ws"].receive_timeout(2000)
        if data is None:
            break
        if mt == 3 and data and data[0] == 0xE3:
            rc = pt.read_short_le(data, 1)
            gs = pt.parse_simple_string(data, 230)
            print(f"{label}: master rc={rc} gs={gs}")
            break
        if mt == 3 and data:
            print(f"{label}: master op {data[0]} rc={pt.read_short_le(data,1)}")
    if not gs:
        print(f"{label}: no gs"); return False

    await st["master_ws"].aclose()
    st["master_ws"] = None
    if not await pt.connect_to_game_server(st, gs):
        print(f"{label}: gs fail"); return False
    await st["master_ws"].send_operation(payload)
    for _ in range(6):
        mt, data = await st["master_ws"].receive_timeout(1200)
        if data is None:
            break
        if mt == 3 and data:
            print(f"{label}: gs op {data[0]} rc={pt.read_short_le(data,1)}")

    res = await asyncio.to_thread(lobby_has, name)
    print(f"{label}: LOBBY = {res}  (room '{name}')")
    ok = res == "YES"
    for _ in range(4):
        await asyncio.sleep(1)
        mt, data = await st["master_ws"].receive_timeout(500)
    await st["master_ws"].aclose()
    return ok


async def main() -> int:
    variants = [
        ("A", dict(visible_params=True, lobby_props=False, flags=1)),
        ("B", dict(visible_params=True, lobby_props=True, flags=1)),
        ("C", dict(visible_params=True, lobby_props=False, flags=0)),
        ("D", dict(visible_params=False, lobby_props=True, flags=0)),
    ]
    for label, kw in variants:
        if await try_variant(label, **kw):
            print(">>> WORKS:", label)
            return 0
        await asyncio.sleep(3)
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))