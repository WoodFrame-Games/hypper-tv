#!/usr/bin/env python3
"""
photon0509.py — клиент Photon (EnetPeer/UDP) для Hypper Sandbox 0.5.0.9.

Единственная точка, где живут параметры подключения и протокол; оба скрипта
(photon_list.py и ptWorkFreeze.py) используют этот модуль.

Параметры (сверены с метадатой 0.5.0.9 и логом клиента):
  AppId       b6c0c507-d9ea-4e0b-ae1a-930bd1240323
  Сервер      82.158.120.189:5055 (UDP, без Name Server/ExitGames)
  AppVersion  0.5.0.9 (Application.version)
  Client      4.1.8.23
  Auth        Custom (217=0), sign = HMAC-SHA256(SECRET_KEY, uid) в hex UPPER
              передаётся как AuthGetParameters (216) = "s=<sign>"

Формат (подробности — PHOTON_GUIDE_0508.md):
  датаграмма [peerId u16 LE][flags u8][cmdCount u8][sentTime u32 BE][challenge u32 BE]
  команда    [type u8][channel u8][flags u8][0x04][size u32 BE][seq u32 BE][payload]
  payload    F3 02 op ...  (запрос) / F3 03 op rc ... (ответ) / F3 04 ev ... (ивент)
  фрагмент   type=8, payload = [startSeq][fragCount][fragNum][totalLen][offset][data]

Зависимостей нет — только стандартная библиотека.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import random
import socket
import struct
import time
import uuid

# ── параметры билда 0.5.0.9 ──────────────────────────────────────────────────
PHOTON_HOST = os.environ.get("HYPPER_PHOTON_HOST", "82.158.120.189")
PHOTON_PORT = int(os.environ.get("HYPPER_PHOTON_PORT", "5055"))
APP_ID = "b6c0c507-d9ea-4e0b-ae1a-930bd1240323"
APP_VER = "0.5.0.9"
CLIENT_VER = "4.1.8.23"
SECRET_KEY = bytes.fromhex("5fbe710fbd13fcf332388fe3dac452b518b9b160ddf689c91d52eb1a69a0604e")

# Известный серверу uid (использовался при вскрытии 0.5.0.8).
# Нужен как фолбэк: сервер отклоняет авторизацию ещё не зарегистрированных
# uid с rc=-2689 (InvalidAuthentication), пока не истечёт лимит регистраций.
FALLBACK_UID = "bc57d0403bb30f8d1deaba727cca5d23"
AUTH_INVALID = -2689      # новый uid серверу неизвестен
AUTH_TOO_MANY = 32757     # "Too many accounts from this address"


def is_uid_rejected(rc: int) -> bool:
    """Сервер не принимает новый uid (лимит регистраций с адреса)."""
    return rc in (AUTH_INVALID, AUTH_TOO_MANY)

# Payload команды CONNECT (32 байта) — как у клиента игры.
CONNECT_PAYLOAD = bytes.fromhex(
    "000004b000008000000000020000000000000000000013880000000200000002"
)

# Типы команд EnetPeer.
(T_ACK, T_CONNECT, T_VERIFY, T_DISCONNECT, T_PING,
 T_RELIABLE, T_UNRELIABLE, T_FRAGMENT) = (1, 2, 3, 4, 5, 6, 7, 8)

MODE_NAMES = {0: "Free", 1: "Private", 2: "Adventure"}

# Ключи параметров Photon (Protocol18 key codes).
KEY_AUTH_GET_PARAMS = 216
KEY_AUTH_TYPE = 217
KEY_APP_VER = 220
KEY_CLIENT_VER = 223
KEY_APP_ID = 224
KEY_USER_ID = 225
KEY_LOBBY_PEER_COUNT = 212
KEY_LOBBY_NAME = 213
KEY_GAME_LIST = 222
KEY_LEAVE = 254

OP_AUTHENTICATE = 230
OP_JOIN_LOBBY = 229

EV_GAME_LIST = 230
EV_GAME_LIST_UPDATE = 229


def default_uid() -> str:
    """Стабильный uid, как deviceUniqueIdentifier у игры (32 hex).

    Порядок: $HYPPER_UID -> файл photon_uid.txt рядом с модулем -> новый guid
    (сохраняется в файл). Случайный uid на каждый запуск сервер воспринимает
    как нового пользователя и после нескольких подключений отвечает
    rc=-2689 (InvalidAuthentication).
    """
    env = os.environ.get("HYPPER_UID")
    if env:
        return env.strip()
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "photon_uid.txt")
    try:
        with open(path, "r", encoding="utf-8") as f:
            saved = f.read().strip()
            if saved:
                return saved
    except OSError:
        pass
    uid = uuid.uuid4().hex
    save_uid(uid)
    return uid


def save_uid(uid: str) -> None:
    """Запоминает uid, чтобы следующие запуски использовали тот же."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "photon_uid.txt")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(uid + "\n")
    except OSError:
        pass


def sign_for(uid: str) -> str:
    """HMAC-SHA256(SECRET_KEY, utf8(uid)) в hex ВЕРХНЕГО регистра."""
    return hmac.new(SECRET_KEY, uid.encode(), hashlib.sha256).hexdigest().upper()


def auth_params(uid: str, app_ver: str = APP_VER) -> list:
    """Параметры операции Authenticate (op 230) для 0.5.0.9."""
    return [
        (KEY_APP_ID, APP_ID),
        (KEY_APP_VER, app_ver),
        (KEY_CLIENT_VER, CLIENT_VER),
        (KEY_USER_ID, uid),
        (KEY_AUTH_TYPE, 0),
        (KEY_AUTH_GET_PARAMS, "s=" + sign_for(uid)),
    ]


# ── Protocol18: запись ──────────────────────────────────────────────────────
def w_varint(buf: bytearray, v: int) -> None:
    while v >= 128:
        buf.append((v & 0x7F) | 0x80)
        v >>= 7
    buf.append(v)


def w_string(buf: bytearray, s: str) -> None:
    raw = s.encode("utf-8")
    buf.append(7)
    w_varint(buf, len(raw))
    buf += raw


def w_int(buf: bytearray, v: int) -> None:
    """Compressed int32 (тип 9) — так клиент пишет обычные int."""
    buf.append(9)
    zig = ((v << 1) ^ (v >> 31)) & 0xFFFFFFFF
    w_varint(buf, zig)


def w_byte(buf: bytearray, v: int) -> None:
    v &= 0xFF
    if v == 0:
        buf.append(0x22)          # ByteZero
    else:
        buf.append(3)
        buf.append(v)


def w_bool(buf: bytearray, v: bool) -> None:
    buf.append(0x1C if v else 0x1B)   # BooleanTrue / BooleanFalse


def w_value(buf: bytearray, v) -> None:
    if isinstance(v, bool):
        w_bool(buf, v)
    elif isinstance(v, str):
        w_string(buf, v)
    elif isinstance(v, (bytes, bytearray)):
        buf.append(7)
        w_varint(buf, len(v))
        buf += v
    elif isinstance(v, int):
        if -128 <= v <= 127:
            w_byte(buf, v)
        else:
            w_int(buf, v)
    else:
        raise TypeError(f"unsupported value {type(v)!r}")


def op_payload(op: int, params=()) -> bytes:
    """Полный payload запроса: F3 02 <op> <count> ([key][type][value])*."""
    buf = bytearray(b"\xf3\x02")
    buf.append(op & 0xFF)
    buf.append(len(params) & 0xFF)
    for key, value in params:
        buf.append(key & 0xFF)
        w_value(buf, value)
    return bytes(buf)


# ── Protocol18: чтение ─────────────────────────────────────────────────────
def r_varint(d: bytes, p: list) -> int:
    v = shift = 0
    while p[0] < len(d):
        b = d[p[0]]
        p[0] += 1
        v |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7
    return v


def _skip(d: bytes, p: list, t: int) -> None:
    if t in (3, 11, 12, 34):      p[0] += 1
    elif t in (4, 13, 14, 29):    p[0] += 2
    elif t == 31:                 p[0] += 4          # ShortZero? -> 4 bytes guard
    elif t == 5:                  p[0] += 4
    elif t == 6:                  p[0] += 8
    elif t in (9, 10):            r_varint(d, p)
    elif t == 7:
        n = r_varint(d, p)
        p[0] += n
    elif t in (67, 120):
        n = r_varint(d, p)
        p[0] += n
    elif t in (20, 21, 104):
        n = r_varint(d, p)
        if p[0] + 2 > len(d):
            return
        kt, vt = d[p[0]], d[p[0] + 1]
        p[0] += 2
        for _ in range(n):
            _skip(d, p, kt)
            _skip(d, p, vt)
    elif t in (23, 122):
        n = r_varint(d, p)
        for _ in range(n):
            if p[0] >= len(d):
                return
            ot = d[p[0]]
            p[0] += 1
            _skip(d, p, ot)
    elif t == 0x47:                  # StringArray
        n = r_varint(d, p)
        for _ in range(n):
            ln = r_varint(d, p)
            p[0] += ln
    elif t in (27, 28, 8, 30):    pass              # bool / null / int-zero
    elif t == 0x22:               pass              # ByteZero


def read_value(d: bytes, p: list):
    """Читает один [type][value]; возвращает python-значение."""
    if p[0] >= len(d):
        return None
    t = d[p[0]]
    p[0] += 1
    if t == 28: return True
    if t == 27: return False
    if t == 8:  return None
    if t == 30: return 0                 # IntZero
    if t == 0x22: return 0               # ByteZero
    if t == 7:
        n = r_varint(d, p)
        s = d[p[0]:p[0] + n].decode("utf-8", "replace")
        p[0] += n
        return s
    if t in (9, 10):
        v = r_varint(d, p)
        return (v >> 1) ^ -(v & 1)      # zigzag int32
    if t in (105, 5):
        v = struct.unpack_from(">i", d, p[0])[0]; p[0] += 4; return v
    if t in (98, 3):
        v = d[p[0]]; p[0] += 1; return v
    if t in (4, 13):
        v = struct.unpack_from(">H", d, p[0])[0]; p[0] += 2; return v
    if t == 14:
        v = -struct.unpack_from(">H", d, p[0])[0]; p[0] += 2; return v
    if t == 11:
        v = d[p[0]]; p[0] += 1; return v
    if t == 12:
        v = -d[p[0]]; p[0] += 1; return v
    if t == 6:
        v = struct.unpack_from(">d", d, p[0])[0]; p[0] += 8; return v
    if t in (20, 21):
        return read_dict(d, p)
    if t == 0x47:                       # StringArray
        n = r_varint(d, p)
        out = []
        for _ in range(n):
            ln = r_varint(d, p)
            out.append(d[p[0]:p[0] + ln].decode("utf-8", "replace"))
            p[0] += ln
        return out
    _skip(d, p, t)
    return "?"


def read_dict(d: bytes, p: list) -> dict:
    """[count varint] ([keyType][key][type][value])* — значения со своим типом."""
    n = r_varint(d, p)
    out = {}
    for _ in range(n):
        if p[0] >= len(d):
            break
        out_key = read_value(d, p)
        out[out_key] = read_value(d, p)
    return out


def parse_room_props(props: dict) -> dict:
    """Свойства комнаты -> компактный dict."""
    info = {}
    for k, v in props.items():
        if k in (255, 243):
            info["max"] = v
        elif k == 252:
            info["players"] = v
        elif k == 254:
            info["visible"] = v
        elif k == 253:
            info["open"] = v
        elif k == 251:
            info["removed"] = v
        elif isinstance(k, str):
            info[k.lower()] = v
    return info


def parse_game_list(payload: bytes) -> dict:
    """Payload ивента GameList/GameListUpdate -> {room: props}."""
    out = {}
    if not payload or payload[:2] != b"\xf3\x04":
        return out
    p = [3]                                  # пропускаем F3 04 <eventCode>
    if p[0] >= len(payload):
        return out
    count = payload[p[0]]
    p[0] += 1
    for _ in range(count):
        if p[0] >= len(payload):
            break
        key = payload[p[0]]
        p[0] += 1
        if key == KEY_GAME_LIST:
            table = read_value(payload, p)
            if isinstance(table, dict):
                for name, props in table.items():
                    if isinstance(props, dict):
                        out[str(name)] = parse_room_props(props)
        else:
            _skip(payload, p, payload[p[0]] if p[0] < len(payload) else 0)
    return out


# ── синхронный клиент ─────────────────────────────────────────────────────
class PhotonUdp:
    """EnetPeer-клиент: CONNECT -> Authenticate -> JoinLobby -> ивенты."""

    MTU = 1200          # как в Photon SDK: больше — режем на FRAGMENT-команды

    def __init__(self, host: str = PHOTON_HOST, port: int = PHOTON_PORT,
                 uid: str | None = None, app_ver: str = APP_VER,
                 timeout: float = 1.5, debug: bool = False):
        self.host, self.port = host, port
        self.uid = uid or default_uid()
        self.app_ver = app_ver
        self.timeout = timeout
        self.debug = debug
        self.sock = None
        self.peer_id = 0xFFFF
        self.challenge = random.getrandbits(32)
        self.t0 = time.time()
        self.seq = {}
        self.frag = {}
        self.pending = {}       # seq -> (cmd_bytes, ts, tries) для ретрансмита
        self.backlog = []       # отложенные не-ACK команды из drain_acks
        self.rooms = {}
        self.alive = False

    # -- низкий уровень ----------------------------------------------------
    def _ms(self) -> int:
        return int((time.time() - self.t0) * 1000) & 0xFFFFFFFF

    def open(self) -> None:
        if self.sock is None:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.settimeout(self.timeout)
            self.alive = True

    def close(self) -> None:
        self.alive = False
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    def _next_seq(self, channel: int) -> int:
        v = self.seq.get(channel, 0) + 1
        self.seq[channel] = v
        return v

    @staticmethod
    def _command(ctype: int, seq: int, payload: bytes = b"",
                 channel: int = 0, flags: int = 1) -> bytes:
        return (bytes([ctype, channel, flags, 4])
                + struct.pack(">II", 12 + len(payload), seq) + payload)

    def _send(self, commands: list) -> None:
        if not self.sock:
            raise RuntimeError("socket closed")
        # всё, что помечено reliable (flags=1), запоминаем до подтверждения
        now = time.time()
        for cmd in commands:
            if len(cmd) >= 12 and cmd[2] == 1:
                seq = struct.unpack_from(">I", cmd, 8)[0]
                self.pending[seq] = (cmd, now, 0)
        pkt = (struct.pack("<HBB", self.peer_id, 0, len(commands))
               + struct.pack(">II", self._ms(), self.challenge)
               + b"".join(commands))
        if self.debug:
            print(">>", pkt.hex(" "))
        self.sock.sendto(pkt, (self.host, self.port))

    def _absorb_ack(self, payload: bytes) -> None:
        if len(payload) < 4:
            return
        acked = struct.unpack_from(">I", payload, 0)[0]
        self.pending.pop(acked, None)

    def drain_acks(self, max_packets: int = 128) -> list:
        """Быстро вычитать подтверждения и вернуть разобранные события."""
        for _ in range(max_packets):
            sent, items = self._read_datagram(0.0)
            if not items:
                break
            self._ack(items, sent)
            for ctype, ch, fl, seq, pl in items:
                if ctype == T_ACK:
                    self._absorb_ack(pl)
                else:
                    self.backlog.append((ctype, ch, fl, seq, pl))
        out = []
        for _ in range(max_packets):
            msgs = self.pump(0.0)
            if not msgs:
                break
            out.extend(msgs)
        return out

    def retransmit(self, max_age: float = 0.35, max_tries: int = 8) -> int:
        """Повторяем reliable-команды, которые сервер не подтвердил."""
        now = time.time()
        sent = 0
        for seq, (cmd, ts, tries) in list(self.pending.items()):
            if now - ts < max_age:
                continue
            if tries >= max_tries:
                self.pending.pop(seq, None)
                continue
            self.pending[seq] = (cmd, now, tries + 1)
            try:
                self.sock.sendto(
                    (struct.pack("<HBB", self.peer_id, 0, 1)
                     + struct.pack(">II", self._ms(), self.challenge) + cmd),
                    (self.host, self.port))
                sent += 1
            except OSError:
                break
        return sent

    def _read_datagram(self, timeout: float):
        """Возвращает (sentTime, [(type, channel, flags, seq, payload)])."""
        self.sock.settimeout(timeout)
        try:
            raw, _ = self.sock.recvfrom(65535)
        except (socket.timeout, TimeoutError):
            return None, []
        except OSError:
            return None, []
        if self.debug:
            print("<<", raw.hex(" "))
        if len(raw) < 12:
            return None, []
        sent = struct.unpack_from(">I", raw, 4)[0]
        count = raw[3]
        off = 12
        out = []
        for _ in range(count):
            if off + 12 > len(raw):
                break
            ctype, ch, fl = raw[off], raw[off + 1], raw[off + 2]
            size, seq = struct.unpack_from(">II", raw, off + 4)
            if size < 12:
                break
            payload = raw[off + 12:min(off + size, len(raw))]
            out.append((ctype, ch, fl, seq, payload))
            off += size
        return sent, out

    def _ack(self, items: list, sent: int | None) -> None:
        acks = []
        for ctype, ch, fl, seq, _pl in items:
            # Подтверждаем все команды с ненулевым seq, кроме самих ACK и PING:
            # иначе сервер бесконечно повторяет доставку (наблюдалось на event 226).
            if ctype in (T_ACK, T_PING) or seq == 0:
                continue
            acks.append(self._command(T_ACK, 0, struct.pack(">II", seq, sent or 0),
                                      channel=ch, flags=0))
        if acks:
            self._send(acks)

    # -- операции ----------------------------------------------------------
    def send_op(self, payload: bytes, channel: int = 0) -> None:
        """Отправляет payload операции (F3 02 …) reliable-командой."""
        if payload[:1] == b"\xf3":
            full = payload
        else:
            full = b"\xf3\x02" + payload          # совместимость со старым build_op()
        # Photon не терпит датаграмм больше MTU: большие события надо резать
        # на FRAGMENT-команды (тип 8), иначе IP-фрагменты теряются и событие
        # молча пропадает (на клиенте игры просто ничего не обновляется).
        limit = self.MTU - 12 - 12 - 20
        if len(full) <= limit:
            self._send([self._command(T_RELIABLE, self._next_seq(channel), full,
                                      channel=channel)])
            return
        total_len = len(full)
        count = (total_len + limit - 1) // limit
        start_seq = self.seq.get(channel, 0) + 1
        for i in range(count):
            off = i * limit
            chunk = full[off:off + limit]
            frag = (struct.pack(">IIIII", start_seq, count, i + 1, total_len, off)
                    + chunk)
            seq = self._next_seq(channel)
            cmd = (bytes([T_FRAGMENT, channel, 1, 4])
                   + struct.pack(">II", 12 + len(frag), seq) + frag)
            self._send([cmd])

    def ping(self) -> None:
        self._send([self._command(T_PING, 0, b"", channel=255, flags=0)])

    # -- приём -------------------------------------------------------------
    def _reassemble(self, pl: bytes):
        if len(pl) < 20:
            return None
        start, total, num, total_len, off = struct.unpack_from(">IIIII", pl, 0)
        data = pl[20:]
        e = self.frag.get(start)
        if e is None:
            e = {"total": total, "buf": bytearray(total_len), "parts": set()}
            self.frag[start] = e
        if off + len(data) <= len(e["buf"]):
            e["buf"][off:off + len(data)] = data
        e["parts"].add(num)
        if len(e["parts"]) >= total:
            del self.frag[start]
            return bytes(e["buf"])
        return None

    def pump(self, timeout: float) -> list:
        """Читает один датаграм, возвращает [(msg_type, data)] прикладного уровня.

        msg_type: 3 = ответ на операцию, 4 = ивент, 5 = disconnect.
        """
        items = getattr(self, "backlog", [])
        if items:
            # сначала отложенные (их накопили drain_acks), иначе при потоке
            # подтверждений они не разбираются никогда
            self.backlog = []
        else:
            sent, items = self._read_datagram(timeout)
            if not items:
                return []
            self._ack(items, sent)
        msgs = []
        for ctype, _ch, _fl, _seq, pl in items:
            if ctype == T_ACK:
                self._absorb_ack(pl)
                continue
            if ctype == T_FRAGMENT:
                whole = self._reassemble(pl)
                if whole is None:
                    continue
                pl = whole
            elif ctype == T_DISCONNECT:
                msgs.append((5, pl[2:] if pl[:1] == b"\xf3" else pl))
                continue
            if not pl or pl[0] != 0xF3:
                continue
            mtype = pl[1]
            if mtype in (2, 3, 4):
                data = pl[2:]
                if mtype == 4:
                    self._absorb_event(data)
                msgs.append((mtype, data))
        return msgs

    def _absorb_event(self, data: bytes) -> None:
        """Обновляет self.rooms по ивентам GameList/GameListUpdate."""
        if not data:
            return
        code = data[0]
        if code not in (EV_GAME_LIST, EV_GAME_LIST_UPDATE):
            return
        table = parse_game_list(b"\xf3\x04" + data)
        if code == EV_GAME_LIST:
            # Ивент 230 — полный снимок видимых комнат.
            self.rooms = {n: p for n, p in table.items() if not p.get("removed")}
        else:
            for name, props in table.items():
                if props.get("removed"):
                    self.rooms.pop(name, None)
                else:
                    self.rooms[name] = props

    # -- сценарий ----------------------------------------------------------
    def connect(self, _host=None, _port=None, *_ignored) -> bool:
        self.open()
        self._send([self._command(T_CONNECT, 1, CONNECT_PAYLOAD, channel=255)])
        for _ in range(6):
            _sent, items = self._read_datagram(self.timeout)
            self._ack(items, _sent)
            for ctype, _ch, _fl, _seq, pl in items:
                if ctype == T_VERIFY and len(pl) >= 2:
                    self.peer_id = struct.unpack_from("<H", pl, 0)[0]
                    if self.debug:
                        print("peerId=0x%04x" % self.peer_id)
                    return True
        return False

    def authenticate(self) -> int:
        self.send_op(op_payload(OP_AUTHENTICATE, auth_params(self.uid, self.app_ver)))
        for _ in range(8):
            for mtype, data in self.pump(self.timeout):
                if mtype == 3 and data and data[0] == OP_AUTHENTICATE:
                    return struct.unpack_from(">h", data, 1)[0]
        return -1

    def join_lobby(self) -> None:
        self.send_op(op_payload(OP_JOIN_LOBBY,
                                [(KEY_LOBBY_NAME, ""), (KEY_LOBBY_PEER_COUNT, 0)]))

    def collect_rooms(self, seconds: float = 10.0, idle: float = 2.5) -> dict:
        """Собирает полный список комнат: ждёт фрагменты, затем тишину idle."""
        deadline = time.time() + seconds
        last = time.time()
        while time.time() < deadline:
            msgs = self.pump(0.5)
            if msgs:
                last = time.time()
            if self.rooms and time.time() - last > idle:
                break
        return dict(self.rooms)

    def session(self) -> bool:
        """connect + authenticate + join_lobby."""
        if not self.connect():
            return False
        if self.authenticate() != 0:
            return False
        self.join_lobby()
        return True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


# ── асинхронная обёртка (для ptWorkFreeze.py) ─────────────────────────────
class AsyncPhotonUdp:
    """Тот же клиент, но с async-интерфейсом старого WS-класса.

    connect()/send_operation()/receive()/receive_timeout()/aclose() —
    блокирующие вызовы уходят в отдельный поток, GIL не мешает.
    """

    def __init__(self, host: str = PHOTON_HOST, port: int = PHOTON_PORT,
                 uid: str | None = None, debug: bool | None = None):
        import threading
        if debug is None:
            debug = os.environ.get("PHOTON_DEBUG") == "1"
        self._c = PhotonUdp(host, port, uid, debug=debug)
        self._lock = threading.Lock()
        self._connected = False
        import collections
        self._queue = collections.deque()

    # -- свойства ----------------------------------------------------------
    @property
    def alive(self) -> bool:
        return self._connected and self._c.sock is not None

    # старые проверки `state["master_ws"]._ws` продолжают работать
    @property
    def _ws(self):
        return self if self.alive else None

    @property
    def peer_id(self) -> int:
        return self._c.peer_id

    @property
    def rooms(self) -> dict:
        return self._c.rooms

    # -- транспорт ---------------------------------------------------------
    async def connect(self, host=None, port=None, *_ignored) -> bool:
        """Только ENET-хендшейк (CONNECT → VERIFYCONNECT).

        Авторизацию и вход в лобби делает вызывающий код — так же, как это
        делал старый WS-класс (иначе операция 230 уходила дважды).
        """
        import asyncio
        if host:
            self._c.host = host
        if port:
            self._c.port = int(port)
        ok = await asyncio.to_thread(self._c.connect)
        self._connected = ok
        return ok

    async def send_operation(self, payload: bytes) -> bool:
        import asyncio
        try:
            with self._lock:
                self._c.send_op(payload)
            return True
        except Exception:
            return False

    async def poll(self, timeout: float = 0.02) -> None:
        """Слить входящие датаграммы: подтверждения + события (в очередь)."""
        import asyncio

        msgs = await asyncio.to_thread(self._c.pump, timeout)
        if msgs:
            self._queue.extend(msgs)

    async def retransmit(self) -> int:
        import asyncio

        return await asyncio.to_thread(self._c.retransmit)

    async def clear_pending(self) -> None:
        self._c.pending.clear()

    async def drain_acks(self) -> list:
        import asyncio

        return await asyncio.to_thread(self._c.drain_acks)

    async def send_ping(self) -> bool:
        import asyncio
        try:
            with self._lock:
                self._c.ping()
            return True
        except Exception:
            return False

    async def send(self, payload: bytes) -> bool:
        """Совместимость со старым кодом: ws._ws.send(<payload>)."""
        return await self.send_operation(payload)

    async def receive(self):
        import asyncio
        if self._queue:
            return self._queue.popleft()
        msgs = await asyncio.to_thread(self._c.pump, self._c.timeout)
        self._queue.extend(msgs)
        return self._queue.popleft() if self._queue else (255, b"")

    async def receive_timeout(self, ms: int):
        import asyncio
        if self._queue:
            return self._queue.popleft()
        msgs = await asyncio.to_thread(self._c.pump, max(0.01, ms / 1000.0))
        self._queue.extend(msgs)
        return self._queue.popleft() if self._queue else (255, b"")

    async def receive_all(self, ms: int) -> list:
        import asyncio
        return await asyncio.to_thread(self._c.pump, max(0.01, ms / 1000.0))

    async def aclose(self) -> None:
        self._connected = False
        self._c.close()

    def close(self) -> None:
        self._connected = False
        self._c.close()


__all__ = [
    "PHOTON_HOST", "PHOTON_PORT", "APP_ID", "APP_VER", "CLIENT_VER", "SECRET_KEY",
    "FALLBACK_UID", "AUTH_INVALID", "AUTH_TOO_MANY", "is_uid_rejected",
    "MODE_NAMES", "PhotonUdp", "AsyncPhotonUdp", "sign_for", "auth_params",
    "op_payload", "parse_game_list", "parse_room_props", "default_uid", "save_uid",
    "OP_AUTHENTICATE", "OP_JOIN_LOBBY", "EV_GAME_LIST", "EV_GAME_LIST_UPDATE",
    "KEY_AUTH_GET_PARAMS", "KEY_AUTH_TYPE", "KEY_APP_VER", "KEY_CLIENT_VER",
    "KEY_APP_ID", "KEY_USER_ID", "KEY_LOBBY_NAME", "KEY_LOBBY_PEER_COUNT",
    "KEY_GAME_LIST", "read_value", "read_dict", "w_value",
]