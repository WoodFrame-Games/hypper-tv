#!/usr/bin/env python3
"""
photon_list.py — список комнат Hypper Sandbox 0.5.0.9 (UDP).

Тонкая обёртка над photon0509.py: вся логика протокола и параметры билда
(AppId, версии, HMAC-подпись, адрес сервера) живут в модуле.

Usage:
    python photon_list.py                      # живой список комнат
    python photon_list.py --uid <32hex>        # свой uid (sign считается локально)
    python photon_list.py --debug              # hex-дамп датаграмм
    python photon_list.py --json               # машинный вывод
    python photon_list.py --host H --port P --ver 0.5.0.9
"""

import argparse
import json
import sys

import photon0509 as ph


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Hypper 0.5.0.9 room list (UDP)")
    ap.add_argument("--host", default=ph.PHOTON_HOST)
    ap.add_argument("--port", type=int, default=ph.PHOTON_PORT)
    ap.add_argument("--uid", default=None, help="UserId (32 hex); по умолчанию новый guid")
    ap.add_argument("--ver", default=ph.APP_VER, help="AppVersion (Application.version)")
    ap.add_argument("--seconds", type=float, default=12.0, help="максимум ожидания списка")
    ap.add_argument("--idle", type=float, default=2.5, help="тишина после последнего ивента")
    ap.add_argument("--json", action="store_true", help="вывести JSON")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    client = ph.PhotonUdp(args.host, args.port, args.uid, app_ver=args.ver, debug=args.debug)
    try:
        if not client.connect():
            print("connect failed: %s:%d" % (args.host, args.port), file=sys.stderr)
            return 1
        rc = client.authenticate()
        if rc != 0 and ph.is_uid_rejected(rc) and client.uid != ph.FALLBACK_UID:
            # Сервер не регистрирует новые uid (rc=-2689) — повторяем с известным.
            print("auth rc=%d для uid=%s; повтор с известным uid…" % (rc, client.uid),
                  file=sys.stderr)
            client.close()
            client = ph.PhotonUdp(args.host, args.port, ph.FALLBACK_UID,
                                  app_ver=args.ver, debug=args.debug)
            if not client.connect():
                print("connect failed: %s:%d" % (args.host, args.port), file=sys.stderr)
                return 1
            rc = client.authenticate()
            if rc == 0:
                ph.save_uid(client.uid)   # запомнить рабочий uid
        if rc != 0:
            print("auth failed: rc=%d (uid=%s, ver=%s)" % (rc, client.uid, args.ver),
                  file=sys.stderr)
            return 2
        client.join_lobby()
        rooms = client.collect_rooms(args.seconds, args.idle)
    finally:
        client.close()

    if args.json:
        print(json.dumps({
            "version": args.ver,
            "server": "%s:%d" % (args.host, args.port),
            "uid": client.uid,
            "peer_id": client.peer_id,
            "count": len(rooms),
            "rooms": rooms,
        }, ensure_ascii=False, indent=2))
        return 0

    print("=== Hypper %s Room List ===" % args.ver)
    print("  %s:%d  uid=%s" % (args.host, args.port, client.uid))
    print("  auth OK, peerId=0x%04x" % client.peer_id)
    print()
    for name in sorted(rooms, key=str.lower):
        r = rooms[name]
        extra = ""
        if r.get("password"):
            extra += " pass=%s" % r["password"]
        if "pvp" in r:
            extra += " pvp=%s" % r["pvp"]
        if "nextbot" in r:
            extra += " nextbot=%s" % r["nextbot"]
        if r.get("onlymodusers"):
            extra += " modsOnly=%s" % r["onlymodusers"]
        mode = ph.MODE_NAMES.get(r.get("gamemode"), r.get("gamemode", "?"))
        print("  %-32s %2s/%-2s  %-9s %-10s%s" % (
            name, r.get("players", "?"), r.get("max", "?"),
            r.get("map", "?"), mode, extra))
    print("-" * 68)
    print("  Всего комнат: %d" % len(rooms))
    return 0


if __name__ == "__main__":
    sys.exit(main())