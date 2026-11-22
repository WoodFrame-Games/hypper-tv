"""Fill test: one Monitor with a red background and green text pixels.

Usage:
    python monitor_fill_test.py --room Fill1 --password 1234 --w 18 --h 10 --size 50

Then join `Fill1` from the game on the phone and take a screenshot. Along a
horizontal line through the monitor you should see:
    black (monitor frame) -> red (screen area not covered by text) -> green (pixels)
That red gap is the empty space we want to remove.
"""

import argparse
import asyncio
import json
import os
import time

import monitor_test as mt
import photon0509 as ph
import ptWorkFreeze as pt


def make_text(w: int, h: int, size: int, fg: str) -> str:
    line = "<b>" + "".join(f"<color={fg}>\u2588</color>" for _ in range(w)) + "</b>"
    return f"<size={size}%>" + "\n".join([line] * h) + "</size>"


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--room", default="FillTest")
    ap.add_argument("--password", default="1234")
    ap.add_argument("--w", type=int, default=18, help="pixels per monitor X")
    ap.add_argument("--h", type=int, default=10, help="pixels per monitor Y")
    ap.add_argument("--size", type=int, default=50)
    ap.add_argument("--sizes", default="",
                    help="comma list, spawn several monitors with different sizes")
    ap.add_argument("--grids", default="",
                    help="comma list WxH@SIZE, e.g. 18x10@50,22x12@42")
    ap.add_argument("--bg", default="#FF0000")
    ap.add_argument("--fg", default="#00FF00")
    ap.add_argument("--x", type=float, default=-2.0)
    ap.add_argument("--y", type=float, default=3.3)
    ap.add_argument("--z", type=float, default=15.0)
    ap.add_argument("--wait", type=float, default=180.0)
    args = ap.parse_args()

    st = pt.make_state("pyfill")
    st["custom_id"] = ph.default_uid()
    st["playfab_id"] = st["custom_id"]
    st["nickname"] = "PyFill"

    if not await pt.connect_to_name_server(st):
        print("connect failed", flush=True)
        return 1
    if not await mt.enter_room(st, args.room, create=True, max_players=10,
                               password=args.password, gamemode=0,
                               max_props=1000, max_vehicles=40):
        print("room failed", flush=True)
        return 2
    print(f"room '{args.room}' created (password {args.password!r}); "
          f"waiting for the phone...", flush=True)

    deadline = time.time() + args.wait
    phone = None
    last_ping = time.time()
    while time.time() < deadline and phone is None:
        msg_type, data = await st["master_ws"].receive_timeout(500)
        if msg_type == 4 and data and data[0] == 255:
            try:
                params = pt.parse_event_data(data).get("params", {})
                actor = params.get(254)
                if isinstance(actor, int) and actor != st.get("actor_nr"):
                    phone = actor
                    print(f"player {actor} joined ({params.get(255)!r})", flush=True)
            except Exception:
                pass
        if time.time() - last_ping > 3.0:
            try:
                await st["master_ws"].send_ping()
            except Exception:
                pass
            last_ping = time.time()

    sizes = ([int(s) for s in args.sizes.split(",") if s.strip()]
             if args.sizes else [args.size])
    if args.grids:
        grids = []
        for part in args.grids.split(","):
            part = part.strip()
            if not part:
                continue
            wh, _, sz = part.partition("@")
            gw, _, gh = wh.partition("x")
            grids.append((int(gw), int(gh), int(sz)))
    else:
        grids = [(args.w, args.h, s) for s in sizes]
    spawned = []
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_fill_test.svn")
    for i, (gw, gh, sz) in enumerate(grids):
        x = args.x + (i - (len(grids) - 1) / 2.0) * 2.2
        text = make_text(gw, gh, sz, args.fg)
        save = mt.build_save(args.bg)
        prop = save["props"][0]
        prop["position"] = {"x": x, "y": args.y, "z": args.z}
        prop["uniqueId"] = mt.unique_id(x, args.y, args.z)
        prop["runtimeData"]["Text"] = text
        prop["runtimeData"]["Color"] = args.bg
        save["props"] = [prop]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(save, f)
        st["_spawned_viewids"] = {}
        st["_spawn_subid"] = i
        await pt.load_save_from_file(st, path, wait_confirm=False)
        vid = (st.get("_spawned_viewids") or {}).get(0)
        print(f"monitor #{i}: {gw}x{gh}@{sz}% view={vid} x={x:.2f} "
              f"({len(text)} chars)", flush=True)
        spawned.append((vid, x, text))
        await asyncio.sleep(0.3)

    print("keep this running; take a screenshot on the phone", flush=True)
    rot = pt.PhotonQuaternion(*mt.MON_ROT)
    end = time.time() + 600
    while time.time() < end:
        for vid, x, text in spawned:
            await st["master_ws"].send_operation(
                pt.build_monitor_sync_payload(
                    vid, pt.PhotonVector3(x, args.y, args.z), rot, True, text,
                    args.bg, cache=None))
        await st["master_ws"].receive_timeout(1200)
        try:
            await st["master_ws"].send_ping()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))