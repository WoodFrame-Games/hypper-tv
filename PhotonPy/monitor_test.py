#!/usr/bin/env python3
"""monitor_test.py — «живая» смена цвета монитора из Python.

Режимы:
  --room NAME       создать комнату и спавнить в ней монитор;
  --join NAME       войти в существующую комнату (например, созданную телефоном)
                    и управлять монитором там.

Каждые --period секунд отправляется новый цвет/текст монитора.
"""

import argparse
import asyncio
import io
import json
import os
import sys
import time

import photon0509 as ph
import ptWorkFreeze as pt

MON_POS = (-2.0, 1.5, 15.0)
MON_ROT = (0.0, 1.0, 0.0, 0.0)
COLORS = [("#F00", "red"), ("#0F0", "green"), ("#00F", "blue"), ("#FF0", "yellow")]


def f32(v: float) -> float:
    import struct
    return struct.unpack("f", struct.pack("f", v))[0]


def unique_id(x: float, y: float, z: float) -> float:
    fx, fy, fz = f32(x), f32(y), f32(z)
    return f32(f32(f32(fx * fx) + f32(fy * fy)) + f32(fz * fz))


def monitor_text(hex_color: str, cols: int = 6, rows: int = 2) -> str:
    line = "".join(f"<color={hex_color}>\u2588</color>" for _ in range(cols))
    body = "\n".join(f"<b>{line}</b>" for _ in range(rows))
    return f"<size=136%>{body}</size>"


def build_save(hex_color: str) -> dict:
    x, y, z = MON_POS
    mon_uid = unique_id(x, y, z)
    cx, cy, cz = x + 1.2, y + 0.6, z
    ctrl_uid = unique_id(cx, cy, cz)
    text = monitor_text(hex_color)
    return {
        "map": "FlatGrass",
        "props": [
            {
                "name": "Monitor",
                "uniqueId": mon_uid,
                "position": {"x": x, "y": y, "z": z},
                "rotation": {"x": MON_ROT[0], "y": MON_ROT[1], "z": MON_ROT[2], "w": MON_ROT[3]},
                "isKinematic": True,
                "instantiationData": None,
                "runtimeData": {
                    "connectedIds": [],
                    "Text": text,
                    "Color": hex_color,
                },
            },
            {
                "name": "MonitorController",
                "uniqueId": ctrl_uid,
                "position": {"x": cx, "y": cy, "z": cz},
                "rotation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
                "isKinematic": True,
                "instantiationData": {"Text": text, "Background color": "Black"},
                "runtimeData": {"connectedIds": [mon_uid], "Signal": False},
            },
        ],
    }


async def enter_room(st: dict, name: str, create: bool, max_players: int = 10,
                     password: str = "", pvp: bool = True,
                     visible: bool = True, open_room: bool = True,
                     gamemode: int = 0, max_props: int = 1000,
                     max_vehicles: int = 40) -> bool:
    """CreateGame (227) либо JoinGame (226) -> реконнект на GS -> та же операция."""
    op = 0xE3 if create else 0xE2
    if create:
        # тот же путь, что и в hold_room.py: полноценный CreateGame с 6 параметрами
        # и PlayerProperties — именно он публикует комнату в лобби.
        payload = pt.build_gs_create_payload(name, pt.build_simple_hashtable(max_players, password, pvp, gamemode,
                                                max_props, max_vehicles), 0,
                                             st.get("nickname", "PyMon"), visible, open_room)
    else:
        req = io.BytesIO()
        req.write(bytes([op, 0x01]))
        req.write(b"\xff\x07")
        raw = name.encode()
        pt.write_varint(req, len(raw))
        req.write(raw)
        payload = req.getvalue()

    await st["master_ws"].send_operation(payload)
    print(("create" if create else "join"), f"'{name}'... ", end="", flush=True)

    gs_addr = None
    for _ in range(15):
        mt, data = await st["master_ws"].receive_timeout(2500)
        if data is None:
            break
        if mt == 255:
            continue
        if mt == 3 and data and data[0] == op:
            rc = pt.read_short_le(data, 1)
            if rc != 0:
                print(f"FAIL rc={rc} {pt.extract_debug_message(data)}")
                return False
            st["gs_token"] = pt.parse_simple_string(data, 221)
            gs_addr = pt.parse_simple_string(data, 230)
            break
    if not gs_addr:
        print("FAIL (no game server address)")
        return False
    print(f"GS:{gs_addr}")

    await st["master_ws"].aclose()
    st["master_ws"] = None
    if not await pt.connect_to_game_server(st, gs_addr):
        return False

    if create:
        payload = pt.build_gs_create_payload(name, pt.build_simple_hashtable(max_players, password, pvp, gamemode,
                                                max_props, max_vehicles), 0,
                                             st.get("nickname", "PyMon"), visible, open_room)
    await st["master_ws"].send_operation(payload)

    for _ in range(20):
        mt, data = await st["master_ws"].receive_timeout(4000)
        if data is None:
            break
        if mt == 255:
            continue
        if mt == 2 and data and data[0] == 255:
            ev = pt.parse_event_data(data)
            actor = ev.get("params", {}).get(254)
            if actor:
                st["actor_nr"] = actor
            print(f"in room (actor={actor})")
            return True
        if mt == 3 and data and data[0] == op:
            rc = pt.read_short_le(data, 1)
            if rc == 0:
                print("in room")
                return True
            print(f"FAIL rc={rc} {pt.extract_debug_message(data)}")
            return False
    print("FAIL (timeout)")
    return False


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--room", default="PyMonitor")
    ap.add_argument("--join", default=None)
    ap.add_argument("--period", type=float, default=3.0)
    ap.add_argument("--seconds", type=float, default=120.0)
    ap.add_argument("--wait-player", type=float, default=0.0,
                    help="ждать входа игрока перед спавном монитора")
    args = ap.parse_args()

    st = pt.make_state("pymon")
    st["custom_id"] = ph.default_uid()
    st["playfab_id"] = st["custom_id"]
    st["nickname"] = "PyMon"

    if not await pt.connect_to_name_server(st):
        print("connect failed")
        return 1
    if not await enter_room(st, args.join or args.room, create=not args.join):
        return 2

    if args.wait_player > 0:
        print(f"waiting for a player to join (up to {args.wait_player}s)...", flush=True)
        deadline = time.time() + args.wait_player
        last_ping = time.time()
        while time.time() < deadline:
            mt, data = await st["master_ws"].receive_timeout(800)
            if data is None:
                break
            if time.time() - last_ping > 3.0:
                try:
                    await st["master_ws"].send_ping()
                except Exception:
                    pass
                last_ping = time.time()
            if mt == 4 and data and data[0] == 226:
                ev = pt.parse_event_data(data)
                actor = ev.get("params", {}).get(254)
                if actor and actor != st.get("actor_nr"):
                    print(f"player {actor} joined -> spawning monitor", flush=True)
                    break
            if mt == 4 and data and data[0] == 255:
                ev = pt.parse_event_data(data)
                actor = ev.get("params", {}).get(254)
                if actor and actor != st.get("actor_nr"):
                    print(f"player {actor} joined -> spawning monitor", flush=True)
                    break
        else:
            print("no player joined, spawning anyway", flush=True)

    save_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_monitor_test.svn")
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(build_save(COLORS[0][0]), f)
    await pt.load_save_from_file(st, save_path)

    vid = (st.get("_spawned_viewids") or {}).get(0)
    print("monitor view id:", vid)
    if not vid:
        print("monitor was not spawned")
        return 3

    pos = pt.PhotonVector3(*MON_POS)
    rot = pt.PhotonQuaternion(*MON_ROT)

    t_end = time.time() + args.seconds
    i = 0
    last_ping = time.time()
    while time.time() < t_end:
        hex_color, name = COLORS[i % len(COLORS)]
        await st["master_ws"].send_operation(
            pt.build_monitor_sync_payload(vid, pos, rot, True, monitor_text(hex_color), hex_color,
                                          cache=5))
        print(f"[{time.strftime('%H:%M:%S')}] monitor -> {name} ({hex_color})", flush=True)
        i += 1

        deadline = time.time() + args.period
        while time.time() < deadline:
            mt, data = await st["master_ws"].receive_timeout(500)
            if data is None:
                break
            if time.time() - last_ping > 3.0:
                try:
                    await st["master_ws"].send_ping()
                except Exception:
                    pass
                last_ping = time.time()
            if mt == 4 and data and data[0] == 255:
                ev = pt.parse_event_data(data)
                actor = ev.get("params", {}).get(254)
                if actor and actor != st.get("actor_nr"):
                    print(f"player joined: {actor} -> resend monitor state")
                    await pt.resend_monitor_states(st, actor)

    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))