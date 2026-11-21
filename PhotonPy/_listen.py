"""Слушаем комнату и печатаем события Monitor (проверка, что Rust шлёт текст)."""
import asyncio
import sys
import time

sys.path.insert(0, r"C:\Work\Hypper\PhotonPy")
import photon0509 as ph
import ptWorkFreeze as pt
import monitor_test as mt


async def main() -> int:
    room = sys.argv[1] if len(sys.argv) > 1 else "RustSix"
    seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 30.0

    st = pt.make_state("listen")
    st["custom_id"] = ph.default_uid()
    st["playfab_id"] = st["custom_id"]
    st["nickname"] = "PyListen"

    if not await pt.connect_to_name_server(st):
        print("connect failed")
        return 1
    if not await mt.enter_room(st, room, create=False):
        print("join failed")
        return 2
    print(f"joined {room!r}, listening {seconds:.0f}s", flush=True)

    end = time.time() + seconds
    seen = 0
    last_ping = time.time()
    while time.time() < end:
        mtype, data = await st["master_ws"].receive_timeout(250)
        if mtype == 4 and data and data[0] == 206:
            ev = pt.parse_event_data(data)
            arr = ev.get("params", {}).get(245)
            text = ""
            view = None
            if isinstance(arr, (list, tuple)) and len(arr) >= 3:
                vd = arr[2]
                if isinstance(vd, (list, tuple)) and len(vd) >= 10:
                    view = vd[0]
                    text = str(vd[9])
            seen += 1
            print(f"  monitor view={view} text={text[:60]!r} (len={len(text)})", flush=True)
        if time.time() - last_ping > 3.0:
            try:
                await st["master_ws"].send_ping()
            except Exception:
                pass
            last_ping = time.time()
    print(f"done, monitor events: {seen}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))