#!/usr/bin/env python3
"""rot_test.py — спавн нескольких PcMonitor с разными поворотами, чтобы найти
правильную ориентацию экрана (по скриншоту телефона)."""
import asyncio
import json
import os
import sys
import time

import photon0509 as ph
import ptWorkFreeze as pt
import monitor_test as mt

ROTS = [
    ("identity", (0.0, 0.0, 0.0, 1.0)),
    ("x+90", (0.7071068, 0.0, 0.0, 0.7071068)),
    ("x-90", (-0.7071068, 0.0, 0.0, 0.7071068)),
    ("x180", (1.0, 0.0, 0.0, 0.0)),
    ("y180", (0.0, 1.0, 0.0, 0.0)),
]

BASE = (-3.0, 1.5, 15.0)
STEP = 1.6


def build_save() -> dict:
    props = []
    for i, (label, rot) in enumerate(ROTS):
        x = BASE[0] + i * STEP
        uid = mt.unique_id(x, BASE[1], BASE[2])
        props.append({
            "name": "Monitor",
            "uniqueId": uid,
            "position": {"x": x, "y": BASE[1], "z": BASE[2]},
            "rotation": {"x": rot[0], "y": rot[1], "z": rot[2], "w": rot[3]},
            "isKinematic": True,
            "instantiationData": None,
            "runtimeData": {
                "connectedIds": [],
                "Text": mt.monitor_text("#0F0"),
                "Color": "#0F0",
            },
        })
    return {"map": "FlatGrass", "props": props}


async def main() -> int:
    room = sys.argv[1] if len(sys.argv) > 1 else "PyRot"
    st = pt.make_state("rot")
    st["custom_id"] = ph.default_uid()
    st["nickname"] = "PyRot"
    if not await pt.connect_to_name_server(st):
        return 1
    if not await mt.enter_room(st, room, create=True):
        print("create failed (maybe exists)")
        return 2

    print("waiting for a player (up to 240s)...", flush=True)
    deadline = time.time() + 240
    last_ping = time.time()
    while time.time() < deadline:
        m, data = await st["master_ws"].receive_timeout(800)
        if data is None:
            break
        if time.time() - last_ping > 3.0:
            try:
                await st["master_ws"].send_ping()
            except Exception:
                pass
            last_ping = time.time()
        if m == 4 and data and data[0] in (226, 255):
            ev = pt.parse_event_data(data)
            actor = ev.get("params", {}).get(254)
            if actor and actor != st.get("actor_nr"):
                print(f"player {actor} joined -> spawning", flush=True)
                break

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_rot_test.svn")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(build_save(), f)
    await pt.load_save_from_file(st, path)
    print("spawned", len(ROTS), "monitors:", [r[0] for r in ROTS], flush=True)

    last_ping = time.time()
    while True:
        m, data = await st["master_ws"].receive_timeout(1000)
        if data is None:
            print("connection closed", flush=True)
            break
        if time.time() - last_ping > 3.0:
            try:
                await st["master_ws"].send_ping()
            except Exception:
                pass
            last_ping = time.time()
        if m == 4 and data and data[0] == 255:
            ev = pt.parse_event_data(data)
            actor = ev.get("params", {}).get(254)
            if actor and actor != st.get("actor_nr"):
                print(f"player {actor} joined -> resend monitor states", flush=True)
                await pt.resend_monitor_states(st, actor)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))