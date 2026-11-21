#!/usr/bin/env python3
"""Самопроверка клиента 0.5.0.9: CONNECT -> Authenticate -> JoinLobby -> JoinGame.

Проверяет, что операции действительно обрабатываются сервером (приходит ответ
F3 03 с кодом), а не только ивенты лобби. Комната заведомо не существует,
ничего не создаётся.

Сервер ограничивает регистрацию новых uid ("Too many accounts from this
address"), поэтому при отказе скрипт повторяет попытку с известным uid.
"""

import struct
import sys

import photon0509 as ph


def open_session(uid: str):
    c = ph.PhotonUdp(uid=uid)
    if not c.connect():
        c.close()
        return None, -1
    rc = c.authenticate()
    if rc != 0:
        c.close()
        return None, rc
    c.join_lobby()
    return c, 0


def main() -> int:
    uid = ph.default_uid()
    c, rc = open_session(uid)
    if c is None and ph.is_uid_rejected(rc) and uid != ph.FALLBACK_UID:
        print("uid %s.. отклонён (rc=%d), повтор с известным uid" % (uid[:8], rc))
        uid = ph.FALLBACK_UID
        c, rc = open_session(uid)
    if c is None:
        print("auth: FAIL rc=%d" % rc)
        return 2

    print("uid:", uid)
    print("sign:", ph.sign_for(uid)[:16] + "...")
    print("connect: OK, peerId=0x%04x" % c.peer_id)
    print("auth: OK")

    c.collect_rooms(seconds=4, idle=1.5)
    print("rooms seen:", len(c.rooms))

    name = "__hypper_selftest"
    c.send_op(ph.op_payload(226, [(255, name)]))
    for _ in range(12):
        for mtype, data in c.pump(1.0):
            if mtype == 3 and data and data[0] == 226:
                print("join('%s') -> rc=%d" % (name, struct.unpack_from(">h", data, 1)[0]))
                c.close()
                return 0
    c.close()
    print("join: no response")
    return 4


if __name__ == "__main__":
    sys.exit(main())