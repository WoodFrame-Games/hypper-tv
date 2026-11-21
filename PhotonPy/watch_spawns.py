#!/usr/bin/env python3
"""watch_spawns.py — войти в комнату, слушать спавны и красить найденный монитор.

Логика:
  * join по имени комнаты;
  * печатаем все события Instantiate/SpаwnObject с именем префаба и view id;
  * как только встретили префаб Monitor — начинаем гонять цвета каждые N секунд.

Телефон должен быть мастером (создать комнату), монитор ставит он же —
наш клиент только перекрашивает.
"""

import argparse
import asyncio
import io
import sys
import time

import photon0509 as ph
import ptWorkFreeze as pt

COLORS = [("#F00", "red"), ("#0F0", "green"), ("#00F", "blue"), ("#FF0", "yellow")]


def monitor_text(hex_color: str, cols: int = 6, rows: int = 2) -> str:
    line = "".join(f"<color={hex_color}>\u2588</color>" for _ in range(cols))
    body = "\n".join(f"<b>{line}</b>" for _ in range(rows))
    return f"<size=136%>{body}</size>"


async def join_room(st: dict, name: str) -> bool:
    req = io.BytesIO()
    req.write(bytes([0xE2, 0x01]))
    req.write(b"\xff\x07")
    pt.write_varint(req, len(name))
    req.write(name.encode())
    payload = req.getvalue()

    await st["master_ws"].send_operation(payload)
    print(f"join '{name}'... ", end="", flush=True)
    gs_addr = None
    for _ in range(15):
        mt, data = await st["master_ws"].receive_timeout(2500)
        if data is None:
            break
        if mt == 255:
            continue
        if mt == 3 and data and data[0] == 0xE2:
            rc = pt.read_short_le(data, 1)
            if rc != 0:
                print(f"FAIL rc={rc}")
                return False
            gs_addr = pt.parse_simple_string(data, 230)
            break
    if not gs_addr:
        print("FAIL (no gs)")
        return False

    await st["master_ws"].aclose()
    st["master_ws"] = None
    if not await pt.connect_to_game_server(st, gs_addr):
        return False
    await st["master_ws"].send_operation(payload)
    for _ in range(15):
        mt, data = await st["master_ws"].receive_timeout(3000)
        if data is None:
            break
        if mt == 2 and data and data[0] == 255:
            print("in room")
            return True
        if mt == 3 and data and data[0] == 0xE2:
            rc = pt.read_short_le(data, 1)
            print("in room" if rc == 0 else f"FAIL rc={rc}")
            return rc == 0
    return False


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--room", required=True)
    ap.add_argument("--period", type=float, default=3.0)
    ap.add_argument("--seconds", type=float, default=600.0)
    args = ap.parse_args()

    st = pt.make_state("watch")
    st["custom_id"] = ph.default_uid()
    st["nickname"] = "PyWatch"
    if not await pt.connect_to_name_server(st):
        return 1
    if not await join_room(st, args.room):
        return 2

    monitor_vid = None
    pos = pt.PhotonVector3(0, 0, 0)
    rot = pt.PhotonQuaternion(0, 0, 0, 1)
    t_end = time.time() + args.seconds
    last_push = 0.0
    idx = 0

    while time.time() < t_end:
        mt, data = await st["master_ws"].receive_timeout(400)
        if data is None:
            print("closed")
            break
        if mt == 255:
            continue
        if mt == 5:
            print("disconnect:", pt.extract_debug_message_at(data, 2))
            break
        if mt == 4 and data:
            ev = data[0]
            if ev == 200:
                info = pt.parse_rpc_info(pt.parse_event_data(data))
                params = info.get("rpc_params") or []
                pname = params[0] if params and isinstance(params[0], str) else None
                vid = info.get("view_id")
                print(f"rpc {info.get('method')} view={vid} prefab={pname}")
                if pname and "monitor" in str(pname).lower():
                    monitor_vid = vid
                    if len(params) >= 3 and isinstance(params[1], pt.PhotonVector3):
                        pos = params[1]
                    if len(params) >= 4 and isinstance(params[2], pt.PhotonQuaternion):
                        rot = params[2]
                    print(f"  -> monitor view={vid} pos={pos.x},{pos.y},{pos.z}")
            elif ev == 202:
                try:
                    info = pt.parse_event_data(data)
                    print("instantiate event:", {k: str(v)[:40] for k, v in info.get("params", {}).items()})
                except Exception as ex:
                    print("inst parse err:", ex)
            elif ev in (255, 254, 226):
                pass
            else:
                print(f"event {ev}")
        if monitor_vid and time.time() - last_push >= args.period:
            hex_color, name = COLORS[idx % len(COLORS)]
            idx += 1
            await st["master_ws"].send_operation(
                pt.build_monitor_sync_payload(monitor_vid, pos, rot, True,
                                              monitor_text(hex_color), hex_color, cache=5))
            print(f"[{time.strftime('%H:%M:%S')}] monitor {monitor_vid} -> {name}", flush=True)
            last_push = time.time()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))