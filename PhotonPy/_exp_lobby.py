#!/usr/bin/env python3
"""Эксперимент: публикация комнаты в лобби (параметры CreateGame)."""
import asyncio
import io
import sys

import photon0509 as ph
import ptWorkFreeze as pt


def build_payload(name: str, ht: bytes, *, lobby_name: bool = True,
                  lobby_props: bool = False, visible_params: bool = False,
                  flags: int = 1) -> bytes:
    buf = io.BytesIO()
    params = 6 + (2 if lobby_name else 0) + (1 if lobby_props else 0) + (2 if visible_params else 0)
    buf.write(bytes([0xE3, params & 0xFF]))
    buf.write(b"\xff\x07")                    # 255 RoomName
    raw = name.encode()
    pt.write_varint(buf, len(raw))
    buf.write(raw)
    if lobby_name:
        buf.write(bytes([0xD5, 0x07, 0x00]))  # 213 LobbyName = ""
        buf.write(bytes([0xD4, 0x0B, 0x00]))  # 212 LobbyType = 0
    buf.write(b"\xfa\x1c")                    # 250 Broadcast = true
    buf.write(b"\xf8")
    buf.write(ht)                              # 248 GameProperties
    buf.write(bytes([0xF1, 0x1B]))             # 241 CleanupCacheOnLeave = false
    buf.write(bytes([0xE8, 0x1C]))             # 232 CheckUserOnJoin = true
    buf.write(bytes([0xBF, 0x0B, flags & 0xFF]))   # 191 RoomOptions flags
    if visible_params:
        buf.write(bytes([0xFE, 0x1C]))         # 254 IsVisible
        buf.write(bytes([0xFD, 0x1C]))         # 253 IsOpen
    if lobby_props:
        buf.write(bytes([0xF9, 0x47]))         # 249 LobbyProperties: string[]
        props = ["Map", "GameMode", "PvP", "Nextbot", "PublicMechanism"]
        pt.write_varint(buf, len(props))
        for s in props:
            b = s.encode()
            pt.write_varint(buf, len(b))
            buf.write(b)
    return buf.getvalue()


def check_lobby(name: str) -> str:
    c = ph.PhotonUdp(uid=ph.default_uid())
    try:
        if not c.connect():
            return "connect-fail"
        rc = c.authenticate()
        if rc != 0:
            return f"auth-fail {rc}"
        c.join_lobby()
        rooms = c.collect_rooms(6, 1.5)
        return "yes" if name in rooms else f"no ({len(rooms)})"
    finally:
        c.close()


async def variant(label: str, name: str, **kw) -> None:
    st = pt.make_state("exp")
    st["custom_id"] = ph.default_uid()
    st["nickname"] = "PyMon"
    if not await pt.connect_to_name_server(st):
        print(f"{label}: connect failed")
        return
    ht = pt.build_simple_hashtable()
    payload = build_payload(name, ht, **kw)
    await st["master_ws"].send_operation(payload)

    gs_addr = None
    for _ in range(10):
        mt, data = await st["master_ws"].receive_timeout(2000)
        if data is None:
            break
        if mt == 3 and data and data[0] == 0xE3:
            rc = pt.read_short_le(data, 1)
            gs_addr = pt.parse_simple_string(data, 230)
            print(f"{label}: master rc={rc} gs={gs_addr}")
            break
    if not gs_addr:
        await st["master_ws"].aclose()
        return

    await st["master_ws"].aclose()
    st["master_ws"] = None
    if not await pt.connect_to_game_server(st, gs_addr):
        print(f"{label}: gs connect failed")
        return
    await st["master_ws"].send_operation(payload)
    for _ in range(10):
        mt, data = await st["master_ws"].receive_timeout(3000)
        if data is None:
            break
        if mt == 2 and data and data[0] == 255:
            print(f"{label}: in room")
            break
        if mt == 3 and data and data[0] == 0xE3:
            print(f"{label}: gs rc={pt.read_short_le(data, 1)}")
            break

    print(f"{label}: lobby={await asyncio.to_thread(check_lobby, name)}")
    await st["master_ws"].aclose()


async def main() -> int:
    await variant("lobbyparam", "PYMON-lp", lobby_name=True)
    await variant("all", "PYMON-all", lobby_name=True, lobby_props=True, visible_params=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))