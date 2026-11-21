#!/usr/bin/env python3
"""
Photon Tool — Python port of the C# Program.cs
Logs into PlayFab, gets a Photon auth token, then connects to Photon
Name Server → Master Server and lets you list / create rooms.

Usage:
    python photon_tool.py [--titleid TITLE] [--appid APPID] [--region REGION] [--ver VERSION]

Requirements:
    pip install websockets aiohttp
"""

import argparse
import asyncio
import io
import platform
import random
import sys
import uuid
import time
import struct
import os
import json
from datetime import datetime

# PlayFab/WebSocket больше не нужны для Photon (0.5.0.9), поэтому тяжёлые
# зависимости необязательны: если они есть — старые хелперы PlayFab работают,
# если нет — соответствующие вызовы просто пропускаются.
try:
    import aiohttp
except ImportError:          # pragma: no cover
    aiohttp = None


# ──────────────────────────── Custom type wrappers ──────────────

class PhotonVector3:
    """Wrapper for Photon Vector3 custom type (code 'V' = 86)."""
    __slots__ = ('x', 'y', 'z')
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x, self.y, self.z = float(x), float(y), float(z)

class PhotonQuaternion:
    """Wrapper for Photon Quaternion custom type (code 'Q' = 81)."""
    __slots__ = ('x', 'y', 'z', 'w')
    def __init__(self, x=0.0, y=0.0, z=0.0, w=1.0):
        self.x, self.y, self.z, self.w = float(x), float(y), float(z), float(w)

class PhotonDictionaryStringObject:
    """Protocol18 Dictionary<string, object>, not Hashtable."""
    __slots__ = ('items',)
    def __init__(self, items: dict | None = None):
        self.items = dict(items or {})

# ──────────────────────────── Prop names ────────────────────────

PROP_NAMES = [
    "Arrow", "Barier", "Barier01", "Barrel", "battery", "Bench_v1", "Block", "Board",
    "BoiteBijou", "Book1", "Book2", "bottle3", "bottle4", "bottleDanger", "bouncy_ball",
    "Box1", "Box2", "Box3", "Box4", "Box_12", "Box_v1", "Bridge21", "Bridge24", "Bush",
    "ButteBus", "Button", "CartonLarge", "CatwalkLong", "CatwalkPillarRails", "CatwalkShort",
    "CeilingClosed", "CeilingSkylight", "ChainlinkBarbwire", "ChainlinkGroup", "ChainlinkSingle",
    "Chair1", "Chevet", "Cone", "Container1", "Container1op", "Container1th", "Container2",
    "Container2op", "Container2th", "CorridorDeadend", "CorridorDeadendWindow", "Crate",
    "c_ck", "decal_013", "decal_014", "decal_015", "decal_016", "decal_017", "Deer",
    "DontEnter", "DoorWood", "door_generic", "door_wood", "Exit", "Fireext", "Floor",
    "FloorTile01", "FloorWood", "FrameWood", "Fridge1", "Gaspump", "Generator", "HelpDesk",
    "Horloge", "Inflatable_boat", "Keyboard", "LampDesk", "LampOffice", "LightPole",
    "lit_double", "MedicBox2", "Mine", "Monitor", "MonitorController", "Mouse", "NoPassing", "Notebook", "OldMonitor",
    "Oxygen_tank", "Parking", "PcMonitor", "Pillar", "PillarWood", "Pills2", "Planters_v1",
    "Planters_v2", "PlatformWood", "Pumpkin", "question_block", "rails_2m", "rails_45",
    "rails_4m", "rails_90", "rail_blockage", "Right", "RoadBend", "RoadBlock", "RoadClosed",
    "RoadCrossroad", "RoadLong", "Rock", "Rock2", "Rock3", "Rock3A", "Rocket", "Roof",
    "RoofMetal", "RoofWood", "SafeFiling", "Seat", "Sign", "SignTraffic", "Sink3",
    "Slippery", "SpeedLimit", "Stol5", "Stool1", "Table", "TableRound", "table_cuisine",
    "Timer", "Tire", "Toilet", "TrafficLight", "tree14A", "tree14B", "TV", "Vase", "VendingMachine",
    "Wall2_10", "Wall2_12", "Wall2_13", "Wall2_15", "Wall2_6", "WallCorner", "WallCorridor",
    "WallPlain", "WallSmall", "WallWindow", "WallWood", "wall_1", "wall_12", "wall_15",
    "wall_2", "wall_3", "wall_32", "wall_3b", "Wall_4", "wall_5", "wall_8", "Wall_door_1",
    "wall_door_m", "Windows_2", "Windows_3", "Windows_5", "Windows_9", "Yield", "YoutubeMonitor",
]


# ──────────────────────────── Config ────────────────────────────
# 0.5.0.9: PlayFab больше не участвует в Photon-авторизации, Name Server и
# WebSocket не используются — прямое UDP-подключение к серверу игры, своя
# HMAC-подпись. Все параметры и протокол — в photon0509.py.

from photon0509 import (          # noqa: E402  (импорт после констант локали)
    AsyncPhotonUdp as PhotonWebSocket,
    APP_ID as PHOTON_APP_ID,
    APP_VER as PHOTON_APP_VER,
    CLIENT_VER as PHOTON_CLIENT_VER,
    PHOTON_HOST,
    PHOTON_PORT,
    KEY_APP_ID,
    KEY_APP_VER,
    KEY_CLIENT_VER,
    KEY_USER_ID,
    KEY_AUTH_TYPE,
    KEY_AUTH_GET_PARAMS,
    OP_AUTHENTICATE,
    OP_JOIN_LOBBY,
    KEY_LOBBY_NAME,
    KEY_LOBBY_PEER_COUNT,
    sign_for,
    FALLBACK_UID,
    AUTH_INVALID,
    AUTH_TOO_MANY,
    is_uid_rejected,
    save_uid,
    default_uid,
)

PLAYFAB_TITLE_ID = "324C5"        # остаётся только для старых вспомогательных вызовов
REGION           = ""             # регион не задаётся: подключение по IP

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
DEFAULT_NICKNAME = "PythonClient"

# ──────────────────────────── State ─────────────────────────────

def make_state(custom_id: str) -> dict:
    """Создаёт чистый словарь состояния для одного клиента (главного или бота)."""
    return {
        "custom_id":       custom_id,
        "session_ticket":  None,
        "playfab_id":      None,
        "photon_token":    None,
        "ns_token":        None,
        "gs_token":        None,
        "master_ws":       None,   # PhotonWebSocket instance
        "on_game_server":  False,
        "running":         True,
        "room_cache":      {},     # кеш комнат: {name: display_string}
        "room_cache_ts":   0,      # время последнего обновления кеша
        "msg_queue":       None,   # asyncio.Queue для всех входящих сообщений
        "room_name":       None,   # имя комнаты, в которой сейчас находится клиент (для ботов)
        "bot_id":          None,   # номер бота (None для главного клиента)
        "bg_tasks":        [],     # фоновые asyncio Task для этого клиента (reader/pinger)
        "event_log":       [],     # последние события GS (для бот-клиентов, без интерактивного ввода)
        "chat_log":        [],     # история сообщений чата
        "debug_events":    [],     # последние сырые события для диагностики
        "chat_view_id":    1,      # ViewID PhotonView чата (обновляется при первом RPC)
        "label":           "main", # человекочитаемая метка клиента для логов
        "nickname":        DEFAULT_NICKNAME,
        "ready":           False,  # True только если логин+токен+лобби прошли полностью успешно
    }


# Главный (интерактивный) клиент — поведение полностью совпадает с исходным скриптом.
state = make_state(None)

# Пул бот-клиентов, создаваемых командой CreateClients. bot_id (int) -> state dict.
bots: dict[int, dict] = {}
_next_bot_id = 1


# ════════════════════════════════════════════════════════════════

def load_config() -> dict:
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception as ex:
        print(f"Config read error: {ex}")
    return {}


def get_config_nickname() -> str:
    data = load_config()
    nick = str(data.get("nickname") or "").strip()
    return nick or DEFAULT_NICKNAME


def save_config_nickname(nickname: str) -> None:
    nick = str(nickname or "").strip() or DEFAULT_NICKNAME
    data = load_config()
    data["nickname"] = nick
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as ex:
        print(f"Config write error: {ex}")
#  PlayFab
# ════════════════════════════════════════════════════════════════

async def playfab_post(path: str, body: dict, ticket: str = None, max_retries: int = 6) -> dict | None:
    if aiohttp is None:
        return None
    url = f"https://{PLAYFAB_TITLE_ID}.playfabapi.com{path}"
    headers = {"Content-Type": "application/json"}
    if ticket:
        headers["X-Authorization"] = ticket
    attempt = 0
    while True:
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                async with session.post(url, json=body, headers=headers) as resp:
                    data = await resp.json(content_type=None)
                    if resp.status == 429 and attempt < max_retries:
                        retry_after = 1.0
                        if isinstance(data, dict) and "retryAfterSeconds" in data:
                            try: retry_after = float(data["retryAfterSeconds"])
                            except (TypeError, ValueError): pass
                        wait = retry_after + random.uniform(0.3, 1.2)  # джиттер, чтобы боты не били одной волной
                        print(f"\n  HTTP 429 (rate limited), retry in {wait:.1f}s [{attempt+1}/{max_retries}]... ", end="", flush=True)
                        await asyncio.sleep(wait)
                        attempt += 1
                        continue
                    if not resp.ok:
                        print(f"\n  HTTP {resp.status}: {str(data)[:200]}")
                        return None
                    return data
        except Exception as ex:
            print(f"\n  HTTP: {ex}")
            return None


def json_get(obj: dict, path: str) -> str | None:
    try:
        for key in path.split("."):
            obj = obj[key]
        return str(obj) if not isinstance(obj, str) else obj
    except (KeyError, TypeError):
        return None


async def playfab_login(state: dict) -> bool:
    """0.5.0.9: PlayFab в Photon-авторизации не участвует.

    �?дентичность клиента — обычный uid (32 hex), подпись считается локально
    HMAC-SHA256 от SECRET_KEY. Функция оставлена ради совместимости с
    остальным кодом (боты, меню).
    """
    if not state.get("custom_id"):
        state["custom_id"] = uuid.uuid4().hex
    state["playfab_id"] = state["custom_id"]
    print(f"[{state['label']}] uid.. {state['custom_id']}")
    return True


async def get_photon_token(state: dict) -> bool:
    """Подпись вместо PlayFab-токена (ключ 216 = 's=<sign>')."""
    uid = state.get("playfab_id") or state.get("custom_id") or uuid.uuid4().hex
    state["photon_token"] = sign_for(uid)
    return True


# ════════════════════════════════════════════════════════════════
#  Binary serialisation helpers
# ════════════════════════════════════════════════════════════════

def write_varint(buf: io.BytesIO, v: int) -> None:
    while v >= 128:
        buf.write(bytes([(v & 0x7F) | 0x80]))
        v >>= 7
    buf.write(bytes([v]))


def read_varint(data: bytes, p: list) -> int:
    """p is a mutable list with one int (pointer)."""
    v, shift = 0, 0
    while True:
        b = data[p[0]]; p[0] += 1
        v |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7
    return v


def write_compressed_int(buf: io.BytesIO, v: int) -> None:
    # Matches Protocol18 WriteCompressedInt32:
    #   IntZero=30, Int1=11(raw), Int1_=12(positive byte), Int2=13(big-endian ushort),
    #   Int2_=14(big-endian negated ushort), CompressedInt=9(zigzag varint)
    if v == 0:        buf.write(b'\x1e');                    return
    if v == -1:       buf.write(b'\x0c\x01');                return
    if v > 0:
        if v <= 255:   buf.write(bytes([0x0b, v]));          return
        if v <= 65535: buf.write(bytes([0x0d, v & 0xFF, (v >> 8) & 0xFF])); return
    else:
        if v >= -255:  buf.write(bytes([0x0c, -v]));         return
        if v >= -65535:
            nv = -v
            buf.write(bytes([0x0e, nv & 0xFF, (nv >> 8) & 0xFF])); return
    buf.write(b'\x09')
    zig = ((v << 1) ^ (v >> 31)) & 0xFFFFFFFF
    while zig >= 128:
        buf.write(bytes([(zig & 0x7F) | 0x80]))
        zig >>= 7
    buf.write(bytes([zig]))


def write_object_array_raw(buf: io.BytesIO, items: list) -> None:
    """Write a Protocol18 ObjectArray (GpType 23)."""
    buf.write(b'\x17')
    write_varint(buf, len(items))
    for item in items:
        _write_value(buf, item)


def write_hashtable_raw(buf: io.BytesIO, entries: list) -> None:
    """Write a Protocol18 Hashtable (GpType 21).
    entries: list of (key, value) pairs.
    """
    buf.write(b'\x15')
    write_varint(buf, len(entries))
    for key, val in entries:
        _write_value(buf, key)
        _write_value(buf, val)


def write_dictionary_string_object_raw(buf: io.BytesIO, data: dict) -> None:
    """Write Protocol18 Dictionary<string, object> (GpType 20)."""
    buf.write(b'\x14')      # Dictionary
    buf.write(b'\x07')      # key type: string
    buf.write(b'\x00')      # value type: object / per-entry typed
    write_varint(buf, len(data))
    for key, val in data.items():
        _write_string(buf, str(key))
        _write_value(buf, val)

def _write_value(buf: io.BytesIO, v) -> None:
    if v is None:
        buf.write(b'\x08'); return
    if isinstance(v, PhotonQuaternion):
        data = struct.pack('>ffff', v.w, v.x, v.y, v.z)
        buf.write(b'\xd1')  # 128 + ord('Q')
        write_varint(buf, len(data))
        buf.write(data); return
    if isinstance(v, PhotonVector3):
        data = struct.pack('>fff', v.x, v.y, v.z)
        buf.write(b'\xd6')  # 128 + ord('V')
        write_varint(buf, len(data))
        buf.write(data); return
    if isinstance(v, str):
        raw = v.encode()
        buf.write(b'\x07')
        write_varint(buf, len(raw))
        buf.write(raw); return
    if isinstance(v, bool):
        buf.write(bytes([0x1c if v else 0x1b])); return
    if isinstance(v, int):
        write_compressed_int(buf, v); return
    if isinstance(v, float):
        buf.write(b'\x05')
        buf.write(struct.pack('>f', v)); return
    if isinstance(v, bytes) and len(v) == 1:
        bv = v[0]
        if bv == 0: buf.write(b'\x22'); return
        buf.write(bytes([0x03, bv])); return
    if isinstance(v, (list, tuple)):
        write_object_array_raw(buf, list(v)); return
    if isinstance(v, PhotonDictionaryStringObject):
        write_dictionary_string_object_raw(buf, v.items); return
    if isinstance(v, dict):
        write_hashtable_raw(buf, list(v.items())); return
    buf.write(b'\x08')


def build_op(op: int, *params) -> bytes:
    """params: list of (key_byte, value) tuples."""
    buf = io.BytesIO()
    buf.write(bytes([op, len(params)]))
    for key, val in params:
        buf.write(bytes([key]))
        _write_value(buf, val)
    return buf.getvalue()


def read_int(data: bytes, p: list, t: int) -> int:
    if t == 9:  return read_varint(data, p)
    if t == 10: read_varint(data, p); return 0
    if t in (105, 5):
        v = int.from_bytes(data[p[0]:p[0]+4], 'big'); p[0] += 4; return v
    if t in (98, 3):   v = data[p[0]]; p[0] += 1; return v
    if t in (4, 13):   v = (data[p[0]] << 8) | data[p[0]+1]; p[0] += 2; return v
    if t == 14:        v = -((data[p[0]] << 8) | data[p[0]+1]); p[0] += 2; return v
    if t == 11:        v = data[p[0]]; p[0] += 1; return v
    if t == 12:        v = -data[p[0]]; p[0] += 1; return v
    if t == 28: return 1
    if t == 27: return 0
    if t in (34, 30): return 0
    return 0


def read_prop_value(data: bytes, p: list, t: int) -> str:
    if t == 7:
        l = read_varint(data, p); s = data[p[0]:p[0]+l].decode(errors='replace'); p[0] += l; return s
    if t == 3:   v = data[p[0]]; p[0] += 1; return str(v)
    if t == 34:  return "0"
    if t == 11:  v = data[p[0]]; p[0] += 1; return str(v)
    if t == 12:  v = -data[p[0]]; p[0] += 1; return str(v)
    if t in (13, 14):
        v = (data[p[0]] << 8) | data[p[0]+1]; p[0] += 2
        if t == 14: v = -v; return str(v)
    if t == 9:   return str(read_varint(data, p))
    if t == 28:  return "true"
    if t == 27:  return "false"
    if t == 30:  return "0"
    skip_value(data, p, t); return "?"


def skip_value(data: bytes, p: list, t: int) -> None:
    if t in (3, 34, 11, 12):         p[0] += 1
    elif t in (4, 13, 14):           p[0] += 2
    elif t == 5:                     p[0] += 4
    elif t == 6:                     p[0] += 8
    elif t in (9, 10):               read_varint(data, p)
    elif t == 7:
        l = read_varint(data, p); p[0] += l
    elif t in (67, 120):
        l = read_varint(data, p); p[0] += l
    elif t in (20, 104):
        if p[0] >= len(data): return
        dk = data[p[0]]; p[0] += 1
        if p[0] >= len(data): return
        dv = data[p[0]]; p[0] += 1
        sz = read_varint(data, p)
        for _ in range(sz):
            if p[0] >= len(data): break
            skip_value(data, p, dk)
            if p[0] >= len(data): break
            skip_value(data, p, dv)
    elif t == 21:
        sz = read_varint(data, p)
        for _ in range(sz):
            if p[0] >= len(data): break
            kt = data[p[0]]; p[0] += 1; skip_value(data, p, kt)
            if p[0] >= len(data): break
            vt = data[p[0]]; p[0] += 1; skip_value(data, p, vt)
    elif t in (23, 122):
        oc = read_varint(data, p)
        for _ in range(oc):
            if p[0] >= len(data): break
            ot = data[p[0]]; p[0] += 1; skip_value(data, p, ot)
    # 27-33 are zero-width tags — nothing to skip


def read_short_be(data: bytes, offset: int) -> int:
    return (data[offset] << 8) | data[offset+1]


def read_short_le(data: bytes, offset: int) -> int:
    v = data[offset] | (data[offset+1] << 8)
    if v >= 0x8000: v -= 0x10000
    return v


# ════════════════════════════════════════════════════════════════
#  Hashtable / room-property builders
# ════════════════════════════════════════════════════════════════

def _write_string(buf: io.BytesIO, s: str) -> None:
    raw = s.encode()
    write_varint(buf, len(raw)); buf.write(raw)


def _write_int_val(buf: io.BytesIO, val: int) -> None:
    write_compressed_int(buf, val)


def write_string_prop(buf: io.BytesIO, key: str, val: str) -> None:
    buf.write(b'\x07'); _write_string(buf, key)
    if not val:  buf.write(b'\x22'); return
    buf.write(b'\x07'); _write_string(buf, val)


def write_int_prop(buf: io.BytesIO, key: str, val: int) -> None:
    buf.write(b'\x07'); _write_string(buf, key)
    _write_int_val(buf, val)


def write_bool_prop(buf: io.BytesIO, key: str, val: bool) -> None:
    buf.write(b'\x07'); _write_string(buf, key)
    buf.write(bytes([0x1c if val else 0x1b]))


def write_byte_entry(buf: io.BytesIO, key: int, val: int) -> None:
    buf.write(bytes([0x03, key, 0x03, val]))


def write_bool_entry(buf: io.BytesIO, key: int, val: bool) -> None:
    buf.write(bytes([0x03, key])); buf.write(bytes([0x1c if val else 0x1b]))


def write_int_entry(buf: io.BytesIO, key: int, val: int) -> None:
    buf.write(bytes([0x03, key])); _write_int_val(buf, val)


def write_string_array_entry(buf: io.BytesIO, key: int, arr: list) -> None:
    buf.write(bytes([0x03, key, 0x47]))   # byte key, StringArray type
    write_varint(buf, len(arr))
    for s in arr:
        if not s:  write_varint(buf, 0); continue
        raw = s.encode(); write_varint(buf, len(raw)); buf.write(raw)


def build_simple_hashtable(max_players: int = 10, password: str = "", pvp: bool = True,
                           gamemode: int = 0, max_props: int = 1000,
                           max_vehicles: int = 40) -> bytes:
    lobby_props = ["Map", "GameMode", "PvP", "Nextbot", "PublicMechanism"]
    if password:
        lobby_props.append("Password")

    buf = io.BytesIO()
    buf.write(b'\x15')          # Hashtable
    write_varint(buf, 17 if password else 16)

    write_byte_entry(buf, 255, max_players)
    write_int_entry(buf, 243, max_players)
    write_bool_entry(buf, 254, True)
    write_bool_entry(buf, 253, True)
    write_string_array_entry(buf, 250, lobby_props)

    write_string_prop(buf, "Map", "FlatGrass")
    write_int_prop(buf,    "GameMode",         gamemode)
    if password:
        write_string_prop(buf, "Password",    password)
    write_int_prop(buf,    "MaxProps",         max_props)
    write_int_prop(buf,    "PropsCount",       0)
    write_int_prop(buf,    "MaxVehicles",      max_vehicles)
    write_int_prop(buf,    "VehiclesCount",    0)
    write_bool_prop(buf,   "PvP",              pvp)
    write_bool_prop(buf,   "RPG",              False)
    write_bool_prop(buf,   "PublicMechanism",  True)
    write_bool_prop(buf,   "Nextbot",          False)
    write_bool_prop(buf,   "OnlyModUsers",     False)
    return buf.getvalue()


# ════════════════════════════════════════════════════════════════
#  Photon transport (0.5.0.9)
# ════════════════════════════════════════════════════════════════
#
# Транспорт — AsyncPhotonUdp из photon0509.py (UDP EnetPeer, без WS и без
# Name Server). �?мпортирован выше под старым именем PhotonWebSocket, чтобы
# весь остальной код (reader/pinger/bots) не пришлось переписывать.


# ════════════════════════════════════════════════════════════════
#  Photon protocol helpers
# ════════════════════════════════════════════════════════════════

def game_mode_name(v: int) -> str:
    return {0: "Free", 1: "Private", 2: "Adventure"}.get(v, str(v))


def extract_debug_message_at(data: bytes, start: int) -> str:
    p = [start]
    if p[0] >= len(data): return ""
    t = data[p[0]]; p[0] += 1
    if t == 7:
        l = read_varint(data, p)
        if p[0] + l <= len(data):
            return data[p[0]:p[0]+l].decode(errors='replace')
    return ""


def extract_debug_message(data: bytes) -> str:
    if data and len(data) >= 4:
        return extract_debug_message_at(data, 3)
    return ""


def parse_disconnect(data: bytes) -> None:
    if not data or len(data) < 2:
        print("  disconnect"); return
    code = read_short_be(data, 0)
    msg  = extract_debug_message_at(data, 2)
    print(f"  disconnect: code={code} msg={msg}")


def parse_master_address(state: dict, data: bytes) -> str | None:
    if not data or len(data) < 4: return None
    state["ns_token"] = None
    master_addr = None
    p = [3]
    dt = data[p[0]]; p[0] += 1
    if dt == 7:
        sl = read_varint(data, p); p[0] += sl
    elif dt not in (8, 0):
        skip_value(data, p, dt)
    if p[0] >= len(data): return None
    pc = data[p[0]]; p[0] += 1
    for _ in range(pc):
        if p[0] + 2 > len(data): break
        k = data[p[0]]; p[0] += 1
        t = data[p[0]]; p[0] += 1
        if k == 230 and t == 7:
            l = read_varint(data, p)
            if p[0] + l <= len(data):
                master_addr = data[p[0]:p[0]+l].decode(errors='replace'); p[0] += l
            continue
        if k == 221 and t == 7:
            l = read_varint(data, p)
            if p[0] + l <= len(data):
                state["ns_token"] = data[p[0]:p[0]+l].decode(errors='replace'); p[0] += l
            continue
        if p[0] > len(data): break
        skip_value(data, p, t)
    return master_addr


def parse_simple_string(data: bytes, target_key: int) -> str | None:
    if not data or len(data) < 4: return None
    p = [3]
    dt = data[p[0]]; p[0] += 1
    if dt == 7:
        sl = read_varint(data, p); p[0] += sl
    elif dt not in (8, 0):
        skip_value(data, p, dt)
    if p[0] >= len(data): return None
    pc = data[p[0]]; p[0] += 1
    for _ in range(pc):
        if p[0] + 2 > len(data): break
        k = data[p[0]]; p[0] += 1
        t = data[p[0]]; p[0] += 1
        if k == target_key and t == 7:
            l = read_varint(data, p)
            if p[0] + l <= len(data):
                return data[p[0]:p[0]+l].decode(errors='replace')
        if p[0] > len(data): break
        skip_value(data, p, t)
    return None


def make_ping() -> bytes:
    """InternalOperationRequest: [0xF3, 6, opCode=1, 1param, key=1, type=9, zigzag(timestamp)]"""
    ts = int(asyncio.get_event_loop().time() * 1000)
    zig = ((ts << 1) ^ (ts >> 31)) & 0xFFFFFFFF
    zig_bytes = bytearray()
    while zig >= 128:
        zig_bytes.append((zig & 0x7F) | 0x80); zig >>= 7
    zig_bytes.append(zig & 0x7F)
    return bytes([0xF3, 0x06, 0x01, 0x01, 0x01, 0x09]) + bytes(zig_bytes)


def merge_room_list(data: bytes, rooms: dict, is_full_list: bool = False) -> None:
    """Обновляет rooms данными из события GameList(230) или GameListUpdate(229).
    Если is_full_list=True — сначала очищает rooms (для события 230).
    Комнаты со свойством Removed удаляются из rooms."""
    if is_full_list:
        rooms.clear()
    p = [2]
    for _ in range(500):
        if p[0] + 2 > len(data): break
        pk = data[p[0]]; p[0] += 1
        pt = data[p[0]]; p[0] += 1
        if pk != 222 or pt != 21:
            skip_value(data, p, pt); continue
        hc = read_varint(data, p)
        for _ in range(hc):
            if p[0] >= len(data): break
            nt = data[p[0]]; p[0] += 1
            room_name = ""
            if nt == 7:
                nl = read_varint(data, p)
                room_name = data[p[0]:p[0]+nl].decode(errors='replace'); p[0] += nl
            else:
                skip_value(data, p, nt); continue
            if not room_name or p[0] >= len(data): continue
            vt = data[p[0]]; p[0] += 1
            if vt != 21: skip_value(data, p, vt); continue
            ec = read_varint(data, p)
            player_count = max_players = 0
            is_open = is_visible = True
            extra = ""
            _removed = None
            for _ in range(ec):
                if p[0] + 2 > len(data): break
                kt = data[p[0]]; p[0] += 1
                prop_key = None; is_byte = False; bk = 0
                if kt == 7:
                    kl = read_varint(data, p)
                    prop_key = data[p[0]:p[0]+kl].decode(errors='replace'); p[0] += kl
                elif kt == 3:
                    bk = data[p[0]]; p[0] += 1; is_byte = True
                elif kt == 34:
                    bk = 0; is_byte = True
                else:
                    skip_value(data, p, kt)
                    if p[0] >= len(data): break
                    vvt = data[p[0]]; p[0] += 1; skip_value(data, p, vvt); continue
                if p[0] >= len(data): break
                vtt = data[p[0]]; p[0] += 1
                if is_byte and bk in (255, 243):  max_players  = read_int(data, p, vtt); continue
                if is_byte and bk == 254:         is_visible   = read_int(data, p, vtt) != 0; continue
                if is_byte and bk == 253:         is_open      = read_int(data, p, vtt) != 0; continue
                if is_byte and bk == 252:         player_count = read_int(data, p, vtt); continue
                if is_byte and bk == 251:         skip_value(data, p, vtt); _removed = room_name; room_name = None; continue
                pv = read_prop_value(data, p, vtt)
                if prop_key == "GameMode":
                    try:    display = game_mode_name(int(pv))
                    except: display = pv
                else:
                    display = pv
                extra += f" {prop_key or f'key{bk}'}={display}"
            if _removed:
                rooms.pop(_removed, None)
            elif room_name:
                flags  = (" [closed]" if not is_open else "") + (" [hidden]" if not is_visible else "")
                rooms[room_name] = f"  [{room_name}] {player_count}/{max_players}{flags}{extra}"


# ════════════════════════════════════════════════════════════════
#  Connection logic
# ════════════════════════════════════════════════════════════════

def _parse_addr(addr: str) -> tuple[str, int, bool, str]:
    """Return (host, port, use_wss, path)."""
    host, port, use_wss, path = addr, 443, True, "/"
    if addr.startswith("ws://"):
        from urllib.parse import urlparse
        u = urlparse(addr); host = u.hostname; port = u.port or 80; use_wss = False; path = u.path or "/"
    elif addr.startswith("wss://"):
        from urllib.parse import urlparse
        u = urlparse(addr); host = u.hostname; port = u.port or 443; path = u.path or "/"
    elif ':' in addr:
        host, p = addr.split(':', 1)
        try: port = int(p)
        except ValueError: pass
    return host, port, use_wss, path


def _build_auth_op_full(state: dict) -> bytes:
    """Authenticate (op 230) для 0.5.0.9: Custom + 's=<HMAC>'."""
    uid = state.get("playfab_id") or state.get("custom_id") or uuid.uuid4().hex
    return build_op(OP_AUTHENTICATE,
        (KEY_APP_ID, PHOTON_APP_ID),
        (KEY_APP_VER, PHOTON_APP_VER),
        (KEY_CLIENT_VER, PHOTON_CLIENT_VER),
        (KEY_USER_ID, uid),
        (KEY_AUTH_TYPE, bytes([0])),          # ClientAuthenticationType = 0 (Custom)
        (KEY_AUTH_GET_PARAMS, "s=" + sign_for(uid)),
    )


async def _open_and_auth(state: dict, uid: str):
    """CONNECT + Authenticate для указанного uid. Возвращает (ws, rc)."""
    ws = PhotonWebSocket(PHOTON_HOST, PHOTON_PORT, uid=uid)
    if not await ws.connect():
        await ws.aclose()
        return None, -1
    auth_state = dict(state)
    auth_state["custom_id"] = uid
    auth_state["playfab_id"] = uid
    await ws.send_operation(_build_auth_op_full(auth_state))
    for _ in range(12):
        msg_type, data = await ws.receive_timeout(900)
        if data is None:
            break
        if msg_type == 5:
            parse_disconnect(data)
            break
        if msg_type == 3 and data and len(data) >= 3:
            if data[0] in (OP_AUTHENTICATE, 231):
                return ws, read_short_le(data, 1)
    await ws.aclose()
    return None, -2


async def connect_to_name_server(state: dict) -> bool:
    """0.5.0.9: вместо Name Server — прямое UDP-подключение к серверу игры.

    Имя функции сохранено: её вызывают и главный клиент, и боты. Делает
    CONNECT -> Authenticate -> JoinLobby и оставляет соединение в
    state["master_ws"]. Если сервер не знает uid (rc=-2689), один раз
    повторяет с известным FALLBACK_UID.
    """
    uid = state.get("custom_id") or uuid.uuid4().hex
    print(f"[{state['label']}] Photon {PHOTON_HOST}:{PHOTON_PORT} (UDP)... ",
          end="", flush=True)

    ws, rc = await _open_and_auth(state, uid)
    if is_uid_rejected(rc) and uid != FALLBACK_UID:
        print(f"uid {uid[:8]}.. не зарегистрирован (rc={rc}), повтор с известным uid... ",
              end="", flush=True)
        uid = FALLBACK_UID
        state["custom_id"] = uid
        state["playfab_id"] = uid
        ws, rc = await _open_and_auth(state, uid)
        if rc == 0:
            save_uid(uid)             # запомнить рабочий uid

    if rc != 0:
        print(f"FAIL (auth rc={rc})")
        return False

    state["master_ws"] = ws
    state["on_game_server"] = False
    print("auth OK")
    await ws.send_operation(build_op(OP_JOIN_LOBBY,
                                     (KEY_LOBBY_NAME, ""),
                                     (KEY_LOBBY_PEER_COUNT, bytes([0]))))
    return True


async def connect_to_master(state: dict, addr: str = "") -> bool:
    """В 0.5.0.9 master и game server — один и тот же узел."""
    return await connect_to_name_server(state)


async def connect_to_game_server(state: dict, addr: str = "") -> bool:
    """Переподключение к игровому серверу (в 0.5.0.9 это тот же узел).

    Сервер отдаёт свой адрес в ответе на CreateGame/JoinGame; адрес может
    совпадать с мастер-сервером — тогда просто открываем новый UDP-peer.
    """
    host, port = PHOTON_HOST, PHOTON_PORT
    if addr:
        h, p, *_ = _parse_addr(addr)
        host = h or host
        port = p or port
    print(f"[{state['label']}] Game Server {host}:{port}... ", end="", flush=True)
    ws = PhotonWebSocket(host, port, uid=state.get("custom_id"))
    if not await ws.connect():
        print("FAIL (connect)"); return False

    await ws.send_operation(
        build_op(230, (221, state["gs_token"])) if state.get("gs_token")
        else _build_auth_op_full(state))
    for _ in range(12):
        msg_type, data = await ws.receive_timeout(900)
        if data is None:
            break
        if msg_type == 5:
            parse_disconnect(data); break
        if msg_type == 3 and data and len(data) >= 3:
            rc = read_short_le(data, 1)
            if data[0] in (OP_AUTHENTICATE, 231):
                if rc != 0:
                    print(f"FAIL (auth rc={rc}) {extract_debug_message(data)}")
                    await ws.aclose(); return False
                state["master_ws"] = ws
                state["on_game_server"] = True
                print("OK")
                return True
    print("FAIL")
    await ws.aclose()
    return False


def _parse_roomchange(cmd_line: str, print_fn=print):
    """Парсит команду изменения комнаты. Возвращает (key, value) или None."""
    parts = cmd_line.split(None, 2)
    if len(parts) < 3:
        print_fn("Usage: /roomchange <key> <value>"); return None
    _, rk, rv = parts
    if rv.lower() == "true": return (rk, True)
    elif rv.lower() == "false": return (rk, False)
    else:
        try: return (rk, int(rv))
        except ValueError: return (rk, rv)


async def _room_cmd_handler(state: dict, cmd_line: str, loop) -> bool:
    """Обрабатывает команду в комнате. Возвращает True если нужно выйти."""
    cmd_lower = cmd_line.strip().lower()
    if cmd_lower in ("leave", "exit", "quit", "q"):
        return True
    if cmd_lower == "help":
        print("Commands: leave, /roomchange <key> <value>, /map, /pvp, /rpg, /day, /nextbot, /gamemode, /maxprops, /maxvehicles, /maxplayers")
        print("Chat:     /SendMessage <text>, /ChatLog, /SetChatViewId <N>, /WhoAmI, /DebugEvents, /Players")
        print("Spawn:    /Spawn <name> [x y z] [rx ry rz rw] [--freeze], /SpawnFor <actor> <name>..., /Props")
        print("Save:     /LoadSave <filename>")
        print("Nickname: /SetNickname <name>, /MyName")
        print("Bots:     /bots, /raiseevent <code> [data], /botraise <bot_id> <code> [data], /botleave <bot_id>, /botsendmessage <bot_id> <text>")
        return False
    if cmd_lower == "":
        return False

    # ── Управление бот-клиентами из консоли комнаты ──
    if cmd_lower == "/bots":
        list_bots()
        return False

    if cmd_lower.startswith("/raiseevent"):
        rest = cmd_line.split(None, 2)[1:]
        if not rest:
            print("Usage: /raiseevent <code 0-255> [data]"); return False
        try:
            code = int(rest[0])
        except ValueError:
            print("code must be an integer 0-255"); return False
        data_val = None
        if len(rest) > 1:
            raw = rest[1]
            if raw.lower() == "true": data_val = True
            elif raw.lower() == "false": data_val = False
            else:
                try: data_val = int(raw)
                except ValueError: data_val = raw
        if state["master_ws"]:
            await state["master_ws"].send_operation(build_raise_event_payload(code, data_val))
            print(f"RaiseEvent code={code} data={data_val} sent from {state['label']}")
        else:
            print("Not connected to game server")
        return False

    if cmd_lower.startswith("/botraise "):
        parts = cmd_line.split(None, 3)
        if len(parts) < 3:
            print("Usage: /botraise <bot_id> <code> [data]"); return False
        try:
            bid = int(parts[1]); code = int(parts[2])
        except ValueError:
            print("bot_id and code must be integers"); return False
        bstate = bots.get(bid)
        if not bstate or not bstate.get("on_game_server") or not bstate.get("master_ws"):
            print(f"bot{bid} is not in a room"); return False
        data_val = None
        if len(parts) > 3:
            raw = parts[3]
            if raw.lower() == "true": data_val = True
            elif raw.lower() == "false": data_val = False
            else:
                try: data_val = int(raw)
                except ValueError: data_val = raw
        await bstate["master_ws"].send_operation(build_raise_event_payload(code, data_val))
        print(f"RaiseEvent code={code} data={data_val} sent from bot{bid}")
        return False

    if cmd_lower.startswith("/botsendmessage ") or cmd_lower.startswith("/botsm "):
        parts = cmd_line.split(None, 2)
        if len(parts) < 2:
            print("Usage: /botsendmessage <bot_id> <text>"); return False
        try:
            bid = int(parts[1])
        except ValueError:
            print("bot_id must be an integer"); return False
        bstate = bots.get(bid)
        if not bstate or not bstate.get("on_game_server") or not bstate.get("master_ws"):
            print(f"bot{bid} is not in a room"); return False
        text = parts[2] if len(parts) > 2 else ""
        if not text:
            print("Usage: /botsendmessage <bot_id> <text>"); return False
        view_id = bstate.get("chat_view_id", 1)
        payload = build_rpc_raise_event_payload(view_id, "PostMassage", text, True)
        await bstate["master_ws"].send_operation(payload)
        print(f"Bot{bid} sent RPC PostMassage: '{text}' (view_id={view_id})")
        return False

    if cmd_lower.startswith("/botleave "):
        try:
            bid = int(cmd_line.split(None, 1)[1].strip())
        except (ValueError, IndexError):
            print("Usage: /botleave <bot_id>"); return False
        bstate = bots.get(bid)
        if not bstate:
            print(f"bot{bid} not found"); return False
        await _stop_bot_background_tasks(bstate)
        if bstate.get("master_ws"):
            await bstate["master_ws"].aclose()
        bstate["master_ws"] = None
        bstate["on_game_server"] = False
        bstate["room_name"] = None
        print(f"bot{bid} left the room (and is now disconnected)")
        return False

    # /roomchange key value — произвольное свойство
    if cmd_lower.startswith("/roomchange ") or cmd_lower.startswith("/rc "):
        kv = _parse_roomchange(cmd_line)
        if kv:
            payload = build_set_properties_payload({kv[0]: kv[1]})
            await state["master_ws"].send_operation(payload)
            print(f"Set {kv[0]}={kv[1]}")
        return False

    # Короткие команды для конкретных свойств
    prefix_map = {
        "/map ":       "Map",
        "/pvp ":       "PvP",
        "/rpg ":       "RPG",
        "/day ":       "Day",
        "/nextbot ":   "Nextbot",
        "/public ":    "PublicMechanism",
        "/password ":  "Password",
    }
    for prefix, prop_key in prefix_map.items():
        if cmd_lower.startswith(prefix):
            val = cmd_line[len(prefix):].strip()
            if val.lower() == "true": val_obj = True
            elif val.lower() == "false": val_obj = False
            else:
                try: val_obj = int(val)
                except ValueError: val_obj = val
            payload = build_set_properties_payload({prop_key: val_obj})
            await state["master_ws"].send_operation(payload)
            print(f"Set {prop_key}={val}")
            return False

    # Числовые свойства
    num_prefixes = {
        "/gamemode ":    "GameMode",
        "/maxprops ":    "MaxProps",
        "/propscount ":  "PropsCount",
        "/maxvehicles ": "MaxVehicles",
        "/vehiclescount ":"VehiclesCount",
    }
    for prefix, prop_key in num_prefixes.items():
        if cmd_lower.startswith(prefix):
            try:
                val = int(cmd_line[len(prefix):].strip())
                payload = build_set_properties_payload({prop_key: val})
                await state["master_ws"].send_operation(payload)
                print(f"Set {prop_key}={val}")
            except ValueError:
                print(f"Invalid number: {cmd_line[len(prefix):].strip()}")
            return False

    if cmd_lower.startswith("/maxplayers "):
        try:
            val = int(cmd_line[len("/maxplayers "):].strip())
            if val <= 0: val = 1
            if val > 255: val = 255
            # Для MaxPlayers нужно менять GamePropertyKey.MaxPlayers (255) и GamePropertyKey.MaxPlayersInt (243)
            payload = build_set_properties_payload({255: val, 243: val})
            await state["master_ws"].send_operation(payload)
            print(f"Set MaxPlayers={val}")
        except ValueError:
            print("Invalid number")
        return False

    if cmd_lower == "/whoami":
        print(f"  label: {state.get('label','?')}")
        print(f"  on_game_server: {state.get('on_game_server')}")
        print(f"  room_name: {state.get('room_name')}")
        print(f"  chat_view_id: {state.get('chat_view_id', 1)}")
        print(f"  chat_log count: {len(state.get('chat_log', []))}")
        return False

    if cmd_lower.startswith("/setchatviewid "):
        try:
            new_id = int(cmd_line[len("/setchatviewid "):].strip())
            if new_id <= 0: new_id = 1
            state["chat_view_id"] = new_id
            print(f"chat_view_id set to {new_id}")
        except ValueError:
            print("Invalid number")
        return False

    if cmd_lower == "/debugevents":
        dev = state.get("debug_events", [])
        if not dev:
            print("(no debug events)")
        else:
            for e in dev[-10:]:
                print(f"  code={e['code']} gt={e['gt']} len={e['len']} hex={e['hex']}")
        return False

    # ── Никнейм ──
    if cmd_lower == "/myname":
        nick = state.get("nickname", "")
        aid = state.get("actor_nr", "?")
        print(f"Actor: {aid}  Nickname: '{nick}'")
        return False

    if cmd_lower.startswith("/setnickname "):
        new_nick = cmd_line[len("/setnickname "):].strip()
        if not new_nick:
            print("Usage: /SetNickname <name>"); return False
        actor_nr = state.get("actor_nr")
        if not actor_nr:
            print("Don't know our actor number yet"); return False
        ht = io.BytesIO()
        write_hashtable_raw(ht, [(bytes([255]), new_nick), ("NickName", new_nick)])
        ht_bytes = ht.getvalue()
        # OpSetPropertiesOfActor (LoadBalancingPeer.cs:706-708):
        #   key 251 = Properties, key 254 = ActorNr, key 250 = Broadcast(true)
        buf = io.BytesIO()
        buf.write(bytes([0xfc, 0x03]))   # op 252 SetProperties, 3 params
        buf.write(bytes([0xfb])); buf.write(ht_bytes)     # key 251 = Properties {255:"nick"}
        buf.write(bytes([0xfe])); _write_value(buf, actor_nr)  # key 254 = ActorNr (!!!)
        buf.write(bytes([0xfa, 0x1c]))                     # key 250 = Broadcast = true
        await state["master_ws"].send_operation(buf.getvalue())
        state["nickname"] = new_nick
        print(f"Set nickname to '{new_nick}' (actor={actor_nr})")
        return False

    if cmd_lower == "/players":
        pl = state.get("players", {})
        if not pl:
            print("(no player data)")
        else:
            for aid, nick in sorted(pl.items()):
                print(f"  Actor {aid}: {nick if nick else '(no nickname)'}")
        print(f"  Our actor: {state.get('actor_nr','?')}, nickname: '{state.get('nickname','')}'")
        return False

    # ── Чат ──
    if cmd_lower == "/chatlog":
        chat_log = state.get("chat_log", [])
        if not chat_log:
            print("(no chat messages received)")
        else:
            for entry in chat_log[-20:]:
                print(f"  {entry}")
        return False

    if cmd_lower.startswith("/sendmessage "):
        text = cmd_line[len("/sendmessage "):].strip()
        if not text:
            print("Usage: /SendMessage <text>"); return False
        view_id = state.get("chat_view_id", 1)
        if state["on_game_server"] and state["master_ws"]:
            payload = build_rpc_raise_event_payload(view_id, "PostMassage", text, True)
            print(f"Sending {len(payload)} bytes for RPC view={view_id}", flush=True)
            await state["master_ws"].send_operation(payload)
            print(f"Sent RPC PostMassage: '{text}' (view_id={view_id})")
        else:
            print("Not on game server")
        return False

    # ── LoadSave ──
    if cmd_lower.startswith("/loadsave ") or cmd_lower.startswith("/load "):
        parts = cmd_line.split(None, 1)
        spath = parts[1].strip() if len(parts) > 1 else ""
        if not spath:
            print("Usage: /LoadSave <filename>")
            return False
        if not os.path.exists(spath) and not spath.endswith('.svn'):
            spath2 = spath + '.svn'
            if os.path.exists(spath2):
                spath = spath2
        if not os.path.exists(spath):
            saves_dir = os.path.join(os.getcwd(), "Saves")
            alt = os.path.join(saves_dir, spath if spath.endswith('.svn') else spath + '.svn')
            if os.path.exists(alt):
                spath = alt
        print(f"Loading save: {spath}")
        state["_spawned_viewids"] = {}
        await load_save_from_file(state, spath)
        return False

    # ── Спавн ──
    if cmd_lower == "/props":
        print("Usage: /Spawn <name>  — доступные префабы пропов:")
        for p in sorted(PROP_NAMES):
            print(f"  {p}")
        return False

    if cmd_lower.startswith("/spawn ") or cmd_lower.startswith("/spawnfor "):
        parts = cmd_line.split()
        owner_actor = 1
        obj_name = ""
        pos = PhotonVector3()
        rot = PhotonQuaternion()
        i = 1
        is_kinematic = False
        extra_data = None
        if parts[0].lower() == "/spawnfor" and len(parts) >= 3:
            try:
                owner_actor = int(parts[1])
            except ValueError:
                print("Usage: /SpawnFor <actorNr> <prefabName>"); return False
            i = 2
        obj_name = parts[i]; i += 1
        if i + 2 < len(parts):
            try:
                pos = PhotonVector3(float(parts[i]), float(parts[i+1]), float(parts[i+2]))
                i += 3
            except ValueError:
                pass
        if i + 3 < len(parts):
            try:
                rot = PhotonQuaternion(float(parts[i]), float(parts[i+1]), float(parts[i+2]), float(parts[i+3]))
                i += 4
            except ValueError:
                pass
        for arg in parts[i:]:
            if arg.lower() == "--freeze":
                is_kinematic = True
            elif arg.lower().startswith("--data="):
                try:
                    parsed = json.loads(arg.split("=", 1)[1])
                    extra_data = parsed if isinstance(parsed, dict) else None
                except Exception:
                    pass
        inst_data = {"isKinematic": is_kinematic}
        if extra_data:
            inst_data.update(extra_data)
        data_arr = [inst_data]
        my_actor = state.get("actor_nr", 0)
        view_id = allocate_spawn_view_id(state, owner_actor)
        ts = int(time.time() * 1000)
        entries = [
            (bytes([0]), obj_name),
            (bytes([1]), pos),
            (bytes([2]), rot),
            (bytes([6]), ts),
            (bytes([7]), view_id),
        ]
        ht = io.BytesIO()
        write_hashtable_raw(ht, entries)
        buf = io.BytesIO()
        buf.write(bytes([0xfd, 0x03]))
        buf.write(bytes([0xf4, 0x03, 202]))
        buf.write(b'\xf5')
        buf.write(ht.getvalue())
        buf.write(bytes([0xf7, 0x03, 0x05]))
        await state["master_ws"].send_operation(buf.getvalue())
        if is_kinematic:
            await state["master_ws"].send_operation(build_freeze_sync_payload(view_id, pos, rot))
        print(f"Spawned '{obj_name}' view={view_id} freeze={is_kinematic}")
        return False

    print("Unknown. 'leave' to exit room.")
    return False


# ════════════════════════════════════════════════════════════════
#  Room operations
# ════════════════════════════════════════════════════════════════

async def _drain_cache(state: dict):
    """Слить накопившиеся события лобби из WS и обновить кеш комнат."""
    ws = state["master_ws"]
    if not ws or not ws._ws or state["on_game_server"]:
        return
    while True:
        gt, gd = await ws.receive_timeout(10)
        if gd is None or gt == 255:
            break
        if gt == 5:
            print(f"\nDisconnected: {extract_debug_message_at(gd, 2)}")
            return
        if gt == 4 and gd:
            ev = gd[0]
            if ev == 230:
                merge_room_list(gd, state["room_cache"], is_full_list=True)
                state["room_cache_ts"] = 1
            elif ev == 229:
                merge_room_list(gd, state["room_cache"])


async def _ensure_lobby(state: dict) -> bool:
    """Ensure we are in lobby; a quiet lobby is still OK if ping works."""
    ws = state["master_ws"]
    if not ws or not ws._ws:
        return False
    try:
        await ws._ws.send(make_ping())
        await ws.send_operation(build_op(229, (213, ""), (212, bytes([0]))))
    except Exception:
        return False
    rooms = dict(state.get("room_cache") or {})
    saw_lobby_response = False
    deadline = time.time() + 6.0
    while time.time() < deadline:
        msg_type, data = await ws.receive_timeout(200)
        if data is None:
            return False
        if msg_type == 255:
            continue
        if msg_type == 5:
            parse_disconnect(data); return False
        if msg_type == 4 and data:
            if data[0] == 230:
                merge_room_list(data, rooms, is_full_list=True)
                saw_lobby_response = True
            elif data[0] == 229:
                merge_room_list(data, rooms)
                saw_lobby_response = True
        elif msg_type in (2, 3):
            saw_lobby_response = True
    state["room_cache"] = rooms
    state["room_cache_ts"] = time.time() if saw_lobby_response or rooms else state.get("room_cache_ts", 0)
    return True

async def interactive_room_list(state: dict, force_refresh: bool = False) -> None:
    if force_refresh or not state["room_cache_ts"]:
        if not state["room_cache_ts"]:
            await _ensure_lobby(state)
        # Дренируем события, ждём полный GameList
        for _ in range(30):
            gt, gd = await state["master_ws"].receive_timeout(200)
            if gd is None: break
            if gt == 255: continue
            if gt == 5: parse_disconnect(gd); return
            if gt == 4 and gd and gd[0] == 230:
                merge_room_list(gd, state["room_cache"], is_full_list=True)
                state["room_cache_ts"] = 1
            elif gt == 4 and gd and gd[0] == 229:
                merge_room_list(gd, state["room_cache"])

    rooms = state["room_cache"]
    if not rooms:
        print("  (no rooms)")
    else:
        for name in sorted(rooms, key=str.lower):
            print(rooms[name])
    print(f"  {len(rooms)} rooms")


def build_gs_create_payload(name: str, ht: bytes, ttl: int = 0, nickname: str = "",
                            visible: bool = True, open_room: bool = True) -> bytes:
    buf = io.BytesIO()
    buf.write(bytes([0xe3]))               # op 227 CreateGame
    nick = str(nickname or "").strip()
    param_count = (7 if ttl > 0 else 6) + (1 if nick else 0) + 2
    buf.write(bytes([param_count]))

    # 255 RoomName
    buf.write(b'\xff\x07')
    raw_name = name.encode()
    write_varint(buf, len(raw_name)); buf.write(raw_name)
    # 250 Broadcast = true
    buf.write(bytes([0xfa, 0x1c]))
    # 248 GameProperties = hashtable
    buf.write(bytes([0xf8])); buf.write(ht)
    # 241 CleanupCacheOnLeave = false
    buf.write(bytes([0xf1, 0x1b]))
    # 232 CheckUserOnJoin = true
    buf.write(bytes([0xe8, 0x1c]))
    # 191 RoomOptionFlags = 1
    buf.write(bytes([0xbf, 0x0b, 0x01]))
    # 254 IsVisible / 253 IsOpen — на уровне операции (не в GameProperties)
    buf.write(bytes([0xfe, 0x1c if visible else 0x1b]))
    buf.write(bytes([0xfd, 0x1c if open_room else 0x1b]))
    if nick:
        ht_player = io.BytesIO()
        write_hashtable_raw(ht_player, [(bytes([255]), nick), ("NickName", nick)])
        buf.write(bytes([0xf9]))  # PlayerProperties
        buf.write(ht_player.getvalue())
    # 236 EmptyRoomTTL (optional)
    if ttl > 0:
        buf.write(bytes([0xec]))
        if ttl <= 255:
            buf.write(bytes([0x0b, ttl]))
        elif ttl <= 65535:
            buf.write(bytes([0x0d, ttl >> 8, ttl & 0xFF]))
        else:
            buf.write(b'\x09')
            zig = ((ttl << 1) ^ (ttl >> 31)) & 0xFFFFFFFF
            while zig >= 128:
                buf.write(bytes([(zig & 0x7F) | 0x80])); zig >>= 7
            buf.write(bytes([zig]))
    return buf.getvalue()


async def create_room(state: dict, name: str, ttl: int = 0) -> None:
    ht = build_simple_hashtable()
    buf = io.BytesIO()
    buf.write(bytes([0xe3, 0x03]))   # op 227, 3 params
    # 255 RoomName
    buf.write(b'\xff\x07')
    raw_name = name.encode()
    write_varint(buf, len(raw_name)); buf.write(raw_name)
    # 248 GameProperties
    buf.write(b'\xf8'); buf.write(ht)
    # 241 CleanupCacheOnLeave = true
    buf.write(bytes([0xf1, 0x1c]))

    ws = state["master_ws"]
    await ws.send_operation(buf.getvalue())
    print(f"Creating '{name}'... ", end="", flush=True)

    for _ in range(15):
        msg_type, data = await ws.receive_timeout(2000)
        if data is None: break
        if msg_type == 255: continue
        if msg_type == 3 and data and len(data) >= 3 and data[0] == 0xe3:
            rc = read_short_le(data, 1)
            if rc == 0:
                state["gs_token"] = parse_simple_string(data, 221)
                gs_addr = parse_simple_string(data, 230)
                if gs_addr:
                    print(f"GS:{gs_addr} ", end="", flush=True)
                    await ws.aclose()
                    state["master_ws"] = None
                    if await connect_to_game_server(state, gs_addr):
                        gs_payload = build_gs_create_payload(name, ht, ttl, state.get("nickname", DEFAULT_NICKNAME))
                        await state["master_ws"].send_operation(gs_payload)
                        joined = False
                        for _ in range(20):
                            gt, gd = await state["master_ws"].receive_timeout(4000)
                            if gd is None: break
                            if gt == 255: continue
                            if gt == 2 and gd and len(gd) >= 2:
                                ev = gd[0]
                                if ev == 255:
                                    # Extract actor number from Join event
                                    ev_data = parse_event_data(gd)
                                    actor_nr = ev_data.get("params", {}).get(254)
                                    if actor_nr and not state.get("actor_nr"):
                                        state["actor_nr"] = actor_nr
                                    print(f"Joined via event (actor={actor_nr})")
                                    joined = True; break
                                print(f"ev{ev} ", end="", flush=True); continue
                            if gt == 3 and gd and len(gd) >= 3:
                                op = gd[0]
                                if op == 0xe3:
                                    gs_rc = read_short_le(gd, 1)
                                    if gs_rc == 0:
                                        print("In room")
                                        joined = True; break
                                    print(f"rc={gs_rc} {extract_debug_message(gd)}"); return
                                print(f"op{op} ", end="", flush=True)
                            if gt == 5: print(f"disc: {extract_debug_message_at(gd,2)}"); return
                        if not joined:
                            print("timeout"); return

                        # ── Keep-alive: пинг + чтение ──
                        print(f"Room '{name}' active. Press Ctrl+C or type 'leave' to exit.")
                        loop = asyncio.get_event_loop()
                        keep_running = True

                        async def _gs_reader():
                            """Читает сообщения от GS (иначе буфер переполняется)."""
                            while keep_running:
                                gt, gd = await state["master_ws"].receive_timeout(3000)
                                if gd is None:
                                    print("\nGame server disconnected.")
                                    return
                                if gt == 5:
                                    print(f"\nDisconnected: {extract_debug_message_at(gd, 2)}")
                                    return
                                # gt == 255 = 0xF0 ping-pong or timeout, ignore
                                # ЛЮБОЙ пришедший тип (2,4,7...) логируем
                                if gd:
                                    state.setdefault("debug_events", []).append({"code": gd[0] if len(gd) > 0 else -1, "gt": gt, "len": len(gd), "hex": gd[:60].hex()})
                                    if len(state["debug_events"]) > 30:
                                        state["debug_events"] = state["debug_events"][-30:]
                                if gt in (2, 4) and gd and len(gd) >= 1:
                                    ev = gd[0]
                                    if ev == 200:
                                        ev_data = parse_event_data(gd)
                                        rpc = parse_rpc_info(ev_data)
                                        vid = rpc.get("view_id")
                                        if vid:
                                            state["chat_view_id"] = vid
                                        rpc_params = rpc.get("rpc_params")
                                        method = rpc.get("method")
                                        shortcut = rpc.get("shortcut")
                                        # detect PostMassage by name OR by params [str, bool]
                                        is_chat = (method == "PostMassage")
                                        if not is_chat and isinstance(rpc_params, (list, tuple)) and len(rpc_params) >= 2:
                                            is_chat = isinstance(rpc_params[0], str) and rpc_params[1] is True
                                        if is_chat:
                                            if rpc_params and len(rpc_params) >= 1:
                                                msg = str(rpc_params[0])
                                                sender = rpc.get("sender")
                                                sender_nick = str(state.get("players", {}).get(str(sender), "")) if sender else ""
                                                prefix = f"[{sender_nick}]" if sender_nick else ""
                                                print(f"\n{prefix} {msg}", flush=True)
                                                state.setdefault("chat_log", []).append(msg)
                                                if len(state["chat_log"]) > 100:
                                                    state["chat_log"] = state["chat_log"][-100:]
                                        else:
                                            m = method or f"shortcut#{shortcut}"
                                            sender = rpc.get("sender", "?")
                                            vid2 = vid or "?"
                                            print(f"\n[RPC {m} view={vid2} sender={sender}]", end="", flush=True)
                                    elif ev == 202:
                                        try:
                                            evp = parse_event_data(gd)
                                            params = evp.get("params", {})
                                            vid = params.get(7)
                                            data_arr = params.get(5)
                                            save_idx = None
                                            if isinstance(data_arr, (list, tuple)) and len(data_arr) > 0 and isinstance(data_arr[0], dict):
                                                save_idx = data_arr[0].get("_saveIdx")
                                            if vid is not None and save_idx is not None:
                                                state.setdefault("_spawned_viewids", {})[save_idx] = vid
                                        except Exception:
                                            pass
                                    elif ev == 255:
                                        try:
                                            evp = parse_event_data(gd)
                                            joined_actor = evp.get("params", {}).get(254)
                                            if joined_actor and joined_actor != state.get("actor_nr"):
                                                schedule_monitor_resync(state, joined_actor)
                                        except Exception:
                                            pass
                                    elif ev in (201, 206):
                                        try:
                                            evp = parse_event_data(gd)
                                            data_arr = evp.get("params", {}).get(245)
                                            if isinstance(data_arr, (list, tuple)) and len(data_arr) >= 3:
                                                ts = data_arr[0]
                                                line = f"\n[Serialize ev={ev} ts={ts}"
                                                for vi in range(2, len(data_arr)):
                                                    vd = data_arr[vi]
                                                    if isinstance(vd, (list, tuple)) and len(vd) >= 5:
                                                        vid = vd[0]; lt = vd[3]; ik = vd[4]
                                                        line += f" view={vid} lt={lt} ik={ik}"
                                                        if len(vd) > 5:
                                                            line += f" +{len(vd)-5}vals"
                                                print(f"{line}]", end="", flush=True)
                                            else:
                                                print(f"\n[GS event {ev} gt={gt} raw={str(data_arr)[:80]}]", end="", flush=True)
                                        except Exception as ex:
                                            print(f"\n[GS event {ev} parse error: {ex}]", end="", flush=True)
                                    elif ev not in (255,):
                                        print(f"\n[GS event {ev} gt={gt}]", end="", flush=True)

                        async def _gs_pinger():
                            """Отправляет пинг каждые 5 секунд — Photon иначе отключает."""
                            while keep_running:
                                await asyncio.sleep(5)
                                if state["master_ws"] and state["master_ws"]._ws:
                                    try:
                                        await state["master_ws"]._ws.send(make_ping())
                                    except Exception:
                                        pass

                        gs_reader = asyncio.ensure_future(_gs_reader())
                        gs_pinger = asyncio.ensure_future(_gs_pinger())

                        try:
                            while keep_running:
                                try:
                                    cmd_line = await loop.run_in_executor(
                                        None, lambda: input("[in room] > ")
                                    )
                                except (EOFError, KeyboardInterrupt):
                                    break
                                if await _room_cmd_handler(state, cmd_line, loop):
                                    break
                        finally:
                            keep_running = False
                            for task in state.pop("_monitor_resync_tasks", []):
                                task.cancel()
                            gs_reader.cancel()
                            gs_pinger.cancel()
                            try:
                                await gs_reader
                            except asyncio.CancelledError:
                                pass
                            try:
                                await gs_pinger
                            except asyncio.CancelledError:
                                pass
                            if state["master_ws"]:
                                await state["master_ws"].aclose()
                                state["master_ws"] = None
                            state["on_game_server"] = False
                            print("Left room. Reconnecting to lobby...")
                            await connect_to_name_server(state)
                    else:
                        print("GS connect failed")
                    return
                print("OK")
            else:
                print(f"fail rc={rc} {extract_debug_message(data)}")
            return
        if msg_type == 5: print(f"disc: {extract_debug_message_at(data,2)}"); return
    print("timeout")


async def join_room(state: dict, name: str) -> None:
    """Присоединиться к существующей комнате."""
    ws = state["master_ws"]
    # JoinGame (226) на MS: только RoomName (PlayerProperties передаются на GS)
    buf = io.BytesIO()
    buf.write(bytes([0xe2, 0x01]))  # op 226, 1 param
    buf.write(b'\xff\x07'); raw = name.encode(); write_varint(buf, len(raw)); buf.write(raw)
    await ws.send_operation(buf.getvalue())
    print(f"Joining '{name}'... ", end="", flush=True)

    for _ in range(15):
        msg_type, data = await ws.receive_timeout(2000)
        if data is None: break
        if msg_type == 255: continue
        if msg_type == 3 and data and len(data) >= 3 and data[0] == 0xe2:
            rc = read_short_le(data, 1)
            if rc == 0:
                state["gs_token"] = parse_simple_string(data, 221)
                gs_addr = parse_simple_string(data, 230)
                if gs_addr:
                    print(f"GS:{gs_addr} ", end="", flush=True)
                    await ws.aclose()
                    state["master_ws"] = None
                    if await connect_to_game_server(state, gs_addr):
                        # JoinGame на GS
                        gs_buf = io.BytesIO()
                        nick = state.get("nickname", "")
                        if nick:
                            gs_buf.write(bytes([0xe2, 0x04]))  # op 226, 4 params
                        else:
                            gs_buf.write(bytes([0xe2, 0x02]))  # op 226, 2 params
                        gs_buf.write(b'\xff\x07'); raw2 = name.encode(); write_varint(gs_buf, len(raw2)); gs_buf.write(raw2)
                        gs_buf.write(bytes([0xe8, 0x1c]))  # CheckUserOnJoin = true
                        if nick:
                            ht_buf = io.BytesIO()
                            write_hashtable_raw(ht_buf, [(bytes([255]), nick), ("NickName", nick)])
                            gs_buf.write(bytes([0xf9]))  # key 249 = PlayerProperties
                            gs_buf.write(ht_buf.getvalue())
                            gs_buf.write(bytes([0xfa, 0x1c]))  # key 250 = Broadcast = true
                        await state["master_ws"].send_operation(gs_buf.getvalue())
                        joined = False
                        for _ in range(20):
                            gt, gd = await state["master_ws"].receive_timeout(4000)
                            if gd is None: break
                            if gt == 255: continue
                            if gt == 2 and gd and len(gd) >= 2:
                                ev = gd[0]
                                if ev == 255:
                                    ev_data = parse_event_data(gd)
                                    actor_nr = ev_data.get("params", {}).get(254)
                                    if actor_nr and not state.get("actor_nr"):
                                        state["actor_nr"] = actor_nr
                                    print(f"Joined! (actor={actor_nr})")
                                    joined = True; break
                                print(f"ev{ev} ", end="", flush=True); continue
                            if gt == 3 and gd and len(gd) >= 3:
                                op = gd[0]
                                if op == 0xe2:
                                    gs_rc = read_short_le(gd, 1)
                                    if gs_rc == 0:
                                        # Parse actor_nr AND player list from OperationResponse params
                                        dm_offset = 3
                                        dm_type = gd[dm_offset] if len(gd) > dm_offset else 8
                                        if dm_type == 8:
                                            p_start = dm_offset + 1
                                        elif dm_type == 7:
                                            p = [dm_offset + 1]
                                            read_varint(gd, p)
                                            p_start = p[0]
                                        else:
                                            p_start = dm_offset + 1
                                        if p_start < len(gd):
                                            try:
                                                pc = gd[p_start] if p_start < len(gd) else 0
                                                pp = [p_start + 1]
                                                players = {}
                                                for _ in range(pc):
                                                    if pp[0] + 2 > len(gd): break
                                                    pk = gd[pp[0]]; pp[0] += 1
                                                    pv = _read_typed_value_at(gd, pp)
                                                    if pk == 254 and not state.get("actor_nr"):  # ActorNr
                                                        state["actor_nr"] = pv
                                                    elif pk == 249:  # PlayerProperties
                                                        if isinstance(pv, dict):
                                                            for actor_key, props in pv.items():
                                                                if isinstance(props, dict):
                                                                    nick = props.get(255) or props.get("NickName") or ""
                                                                    players[str(actor_key)] = nick
                                                if players:
                                                    state["players"] = players
                                                    print(f"\n  Players in room: {', '.join(f'{k}={v}' for k,v in sorted(players.items()))}")
                                            except Exception as ex:
                                                print(f"\n  parse error: {ex}")
                                        print(f"In room (actor={state.get('actor_nr','?')})")
                                        joined = True; break
                                    print(f"rc={gs_rc} {extract_debug_message(gd)}"); return
                            if gt == 5: print(f"disc: {extract_debug_message_at(gd,2)}"); return
                        if not joined:
                            print("timeout"); return

                        # Keep-alive
                        print(f"Room '{name}' active. Press Ctrl+C or type 'leave' to exit.")
                        loop = asyncio.get_event_loop()
                        keep_running = True

                        async def _gs_reader():
                            while keep_running:
                                gt, gd = await state["master_ws"].receive_timeout(3000)
                                if gd is None: print("\nGame server disconnected."); return
                                if gt == 5: print(f"\nDisconnected: {extract_debug_message_at(gd, 2)}"); return
                                if gd:
                                    state.setdefault("debug_events", []).append({"code": gd[0] if len(gd) > 0 else -1, "gt": gt, "len": len(gd), "hex": gd[:60].hex()})
                                    if len(state["debug_events"]) > 30:
                                        state["debug_events"] = state["debug_events"][-30:]
                                # actor_nr from any Join event
                                if gt in (2, 4) and gd and len(gd) >= 1 and gd[0] == 255:
                                    ev_data = parse_event_data(gd)
                                    prev_actor_nr = state.get("actor_nr")
                                    anr = ev_data.get("params", {}).get(254)
                                    if anr and not state.get("actor_nr"):
                                        state["actor_nr"] = anr
                                    # parse player properties from Join event
                                    props = ev_data.get("params", {}).get(249)
                                    if isinstance(props, dict):
                                        pl = state.setdefault("players", {})
                                        for k, v in props.items():
                                            if isinstance(v, dict):
                                                nick = v.get(255) or v.get("NickName") or ""
                                                pl[str(k)] = nick
                                    if anr and anr != state.get("actor_nr"):
                                        schedule_monitor_resync(state, anr)
                                if gt in (2, 4) and gd and len(gd) >= 1:
                                    ev = gd[0]
                                    if ev == 200:
                                        ev_data = parse_event_data(gd)
                                        rpc = parse_rpc_info(ev_data)
                                        vid = rpc.get("view_id")
                                        if vid:
                                            state["chat_view_id"] = vid
                                        rpc_params = rpc.get("rpc_params")
                                        method = rpc.get("method")
                                        shortcut = rpc.get("shortcut")
                                        is_chat = (method == "PostMassage")
                                        if not is_chat and isinstance(rpc_params, (list, tuple)) and len(rpc_params) >= 2:
                                            is_chat = isinstance(rpc_params[0], str) and rpc_params[1] is True
                                        if is_chat:
                                            if rpc_params and len(rpc_params) >= 1:
                                                msg = str(rpc_params[0])
                                                sender = rpc.get("sender")
                                                sender_nick = str(state.get("players", {}).get(str(sender), "")) if sender else ""
                                                prefix = f"[{sender_nick}]" if sender_nick else ""
                                                print(f"\n{prefix} {msg}", flush=True)
                                                state.setdefault("chat_log", []).append(msg)
                                                if len(state["chat_log"]) > 100:
                                                    state["chat_log"] = state["chat_log"][-100:]
                                        else:
                                            m = method or f"shortcut#{shortcut}"
                                            sender = rpc.get("sender", "?")
                                            vid2 = vid or "?"
                                            print(f"\n[RPC {m} view={vid2} sender={sender}]", end="", flush=True)
                                    elif ev == 202:
                                        try:
                                            evp = parse_event_data(gd)
                                            params = evp.get("params", {})
                                            vid = params.get(7)
                                            data_arr = params.get(5)
                                            save_idx = None
                                            if isinstance(data_arr, (list, tuple)) and len(data_arr) > 0 and isinstance(data_arr[0], dict):
                                                save_idx = data_arr[0].get("_saveIdx")
                                            if vid is not None and save_idx is not None:
                                                state.setdefault("_spawned_viewids", {})[save_idx] = vid
                                        except Exception:
                                            pass
                                    elif ev in (201, 206):
                                        try:
                                            evp = parse_event_data(gd)
                                            data_arr = evp.get("params", {}).get(245)
                                            if isinstance(data_arr, (list, tuple)) and len(data_arr) >= 3:
                                                ts = data_arr[0]
                                                prefix = data_arr[1]
                                                line = f"\n[Serialize ev={ev} ts={ts}"
                                                for vi in range(2, len(data_arr)):
                                                    vd = data_arr[vi]
                                                    if isinstance(vd, (list, tuple)) and len(vd) >= 5:
                                                        vid = vd[0]; lt = vd[3]; ik = vd[4]
                                                        line += f" view={vid} lt={lt} ik={ik}"
                                                        if len(vd) > 5:
                                                            line += f" +{len(vd)-5}vals"
                                                print(f"{line}]", end="", flush=True)
                                            else:
                                                print(f"\n[GS event {ev} gt={gt} raw={str(data_arr)[:80]}]", end="", flush=True)
                                        except Exception as ex:
                                            print(f"\n[GS event {ev} parse error: {ex}]", end="", flush=True)
                                    elif ev not in (255,):
                                        print(f"\n[GS event {ev} gt={gt}]", end="", flush=True)

                        async def _gs_pinger():
                            while keep_running:
                                await asyncio.sleep(5)
                                if state["master_ws"] and state["master_ws"]._ws:
                                    try: await state["master_ws"]._ws.send(make_ping())
                                    except Exception: pass

                        gs_reader = asyncio.ensure_future(_gs_reader())
                        gs_pinger = asyncio.ensure_future(_gs_pinger())
                        try:
                            while keep_running:
                                try: cmd_line = await loop.run_in_executor(None, lambda: input("[in room] > "))
                                except (EOFError, KeyboardInterrupt): break
                                if await _room_cmd_handler(state, cmd_line, loop): break
                        finally:
                            keep_running = False
                            for task in state.pop("_monitor_resync_tasks", []):
                                task.cancel()
                            gs_reader.cancel(); gs_pinger.cancel()
                            try: await gs_reader
                            except asyncio.CancelledError: pass
                            try: await gs_pinger
                            except asyncio.CancelledError: pass
                            if state["master_ws"]: await state["master_ws"].aclose(); state["master_ws"] = None
                            state["on_game_server"] = False
                            print("Left room. Reconnecting to lobby...")
                            await connect_to_name_server(state)
                    else:
                        print("GS connect failed")
                else:
                    print("OK (joined)")
                return
            else:
                print(f"fail rc={rc} {extract_debug_message(data)}")
                return
        if msg_type == 5: print(f"disc: {extract_debug_message_at(data,2)}"); return
    print("timeout")


def build_set_properties_payload(props: dict) -> bytes:
    """OpSetProperties (252) с одной парой ключ-значение в Hashtable (251).
    props = {"Map": "Desert"} или {"PvP": True} и т.д."""
    buf = io.BytesIO()
    buf.write(bytes([0xfc, 0x01]))  # op 252, 1 param
    buf.write(bytes([0xfb]))        # key 251 = Properties
    buf.write(b'\x15')              # Hashtable type
    write_varint(buf, len(props))   # number of entries
    for key, val in props.items():
        # key as string
        if isinstance(key, str):
            buf.write(b'\x07')
            raw_key = key.encode()
            write_varint(buf, len(raw_key)); buf.write(raw_key)
        else:
            buf.write(bytes([0x03, key]))
        # value
        if isinstance(val, bool):
            buf.write(bytes([0x1c if val else 0x1b]))
        elif isinstance(val, int):
            if val == 0: buf.write(b'\x1e')
            elif 0 < val <= 255: buf.write(bytes([0x0b, val]))
            else:
                buf.write(b'\x09')
                zig = ((val << 1) ^ (val >> 31)) & 0xFFFFFFFF
                while zig >= 128: buf.write(bytes([(zig & 0x7F) | 0x80])); zig >>= 7
                buf.write(bytes([zig]))
        elif isinstance(val, str):
            if not val: buf.write(b'\x22')
            else: buf.write(b'\x07'); raw_val = val.encode(); write_varint(buf, len(raw_val)); buf.write(raw_val)
        else:
            buf.write(b'\x08')  # null
    return buf.getvalue()


# ════════════════════════════════════════════════════════════════
#  Bot clients — для нагрузочного тестирования собственного сервера
# ════════════════════════════════════════════════════════════════

BOT_LOGIN_CONCURRENCY = 3  # сколько ботов логинятся в PlayFab одновременно (поднимите, если у вашего тайтла лимит выше)


async def _bot_login_and_lobby(bot_id: int) -> dict:
    """Полный цикл для одного бота: PlayFab login -> Photon token -> NameServer -> Master -> JoinLobby.
    state["ready"] становится True только если ВСЕ шаги прошли успешно."""
    custom_id = f"{platform.node()}_bot{bot_id}_{uuid.uuid4().hex[:8]}"
    bstate = make_state(custom_id)
    bstate["bot_id"] = bot_id
    bstate["label"] = f"bot{bot_id}"
    try:
        if not await playfab_login(bstate):
            return bstate
        if not await get_photon_token(bstate):
            return bstate
        if not await connect_to_name_server(bstate):
            return bstate
        if not await _ensure_lobby(bstate):
            print(f"[bot{bot_id}] lobby join failed")
            if bstate["master_ws"]:
                await bstate["master_ws"].aclose()
            bstate["master_ws"] = None
            return bstate
        bstate["ready"] = True
        # [FIX] Запускаем фоновый reader + pinger для поддержания соединения в лобби
        _start_bot_background_tasks(bstate)
    except Exception as ex:
        print(f"[bot{bot_id}] exception: {ex}")
    return bstate


async def create_clients(n: int) -> None:
    """Создаёт N бот-клиентов: логин в PlayFab + авторизация в Photon + вход в лобби.
    Боты не присоединяются к комнате автоматически — для этого используйте JoinAll."""
    global _next_bot_id
    if n <= 0:
        print("N must be > 0"); return
    print(f"Creating {n} bot client(s) (concurrency={BOT_LOGIN_CONCURRENCY})...")
    ids = list(range(_next_bot_id, _next_bot_id + n))
    _next_bot_id += n

    sem = asyncio.Semaphore(BOT_LOGIN_CONCURRENCY)
    results: dict[int, dict] = {}

    async def _worker(bid):
        async with sem:
            results[bid] = await _bot_login_and_lobby(bid)

    await asyncio.gather(*(_worker(bid) for bid in ids))

    ok = 0
    for bid in ids:
        bstate = results[bid]
        bots[bid] = bstate
        if bstate.get("ready"):
            ok += 1
            print(f"  bot{bid}: OK ({bstate['playfab_id']})")
        else:
            print(f"  bot{bid}: FAILED")
    print(f"Done: {ok}/{n} bots connected and in lobby. Total bots: {len(bots)}.")


def _start_bot_background_tasks(state: dict) -> None:
    """Фоновый reader/pinger для бота, который сидит в комнате без интерактивного ввода."""
    # [FIX] Не запускаем задачи повторно
    if state.get("bg_tasks"):
        return
    keep = {"running": True}

    async def _reader():
        while keep["running"]:
            ws = state["master_ws"]
            if not ws or not ws._ws:
                await asyncio.sleep(0.5)
                continue
            gt, gd = await ws.receive_timeout(3000)
            if gd is None:
                state["event_log"].append("disconnected")
                state["on_game_server"] = False
                return
            if gt == 5:
                state["event_log"].append(f"disc: {extract_debug_message_at(gd, 2)}")
                state["on_game_server"] = False
                return
            if gt == 2 and gd and len(gd) >= 1:
                ev = gd[0]
                if ev == 200:
                    rpc = parse_rpc_info(parse_event_data(gd))
                    vid = rpc.get("view_id")
                    if vid:
                        state["chat_view_id"] = vid
                    if rpc.get("method") == "PostMassage":
                        rpc_params = rpc.get("rpc_params", [])
                        if rpc_params and len(rpc_params) >= 1:
                            msg = str(rpc_params[0])
                            state.setdefault("chat_log", []).append(msg)
                            if len(state["chat_log"]) > 100:
                                state["chat_log"] = state["chat_log"][-100:]
                if ev == 202:
                    try:
                        evp = parse_event_data(gd)
                        params = evp.get("params", {})
                        vid = params.get(7)
                        data_arr = params.get(5)
                        save_idx = None
                        if isinstance(data_arr, (list, tuple)) and len(data_arr) > 0 and isinstance(data_arr[0], dict):
                            save_idx = data_arr[0].get("_saveIdx")
                        if vid is not None and save_idx is not None:
                            state.setdefault("_spawned_viewids", {})[save_idx] = vid
                    except Exception:
                        pass
                if ev not in (255,):
                    state["event_log"].append(f"event {ev}")
                    if len(state["event_log"]) > 50:
                        state["event_log"].pop(0)

    async def _pinger():
        while keep["running"]:
            await asyncio.sleep(5)
            ws = state["master_ws"]
            if ws and ws._ws:
                try:
                    await ws._ws.send(make_ping())
                except Exception:
                    pass

    t1 = asyncio.ensure_future(_reader())
    t2 = asyncio.ensure_future(_pinger())
    state["bg_tasks"] = [keep, t1, t2]


async def _stop_bot_background_tasks(state: dict) -> None:
    items = state.get("bg_tasks") or []
    for item in items:
        if isinstance(item, dict):
            item["running"] = False
    for item in items:
        if hasattr(item, "cancel"):
            item.cancel()
            try:
                await item
            except asyncio.CancelledError:
                pass
    state["bg_tasks"] = []


# [NEW] Функция проверки и переподключения бота
async def _ensure_bot_connected(state: dict) -> bool:
    """Проверяет соединение бота с мастером и переподключает, если оно разорвано."""
    if not state.get("master_ws"):
        # Нет сокета – подключаемся заново
        print(f"[{state['label']}] reconnecting to master...")
        return await connect_to_name_server(state)
    # Сокет есть, но может быть мёртв
    if not await _check_connection(state):
        print(f"[{state['label']}] connection stale, reconnecting...")
        if state["master_ws"]:
            await state["master_ws"].aclose()
            state["master_ws"] = None
        return await connect_to_name_server(state)
    return True


async def bot_join_room(state: dict, name: str) -> bool:
    """Присоединяет бота к существующей комнате и оставляет его там 'болванчиком',
    обрабатывая события в фоне — без интерактивной консоли (та занята главным клиентом)."""
    # [FIX] Убедимся, что соединение живо, при необходимости переподключим
    if not await _ensure_bot_connected(state):
        print(f"[{state['label']}] cannot connect to master")
        return False

    ws = state["master_ws"]
    if not ws:
        return False

    buf = io.BytesIO()
    buf.write(bytes([0xe2, 0x01]))  # op 226 JoinGame, 1 param
    buf.write(b'\xff\x07'); raw = name.encode(); write_varint(buf, len(raw)); buf.write(raw)
    await ws.send_operation(buf.getvalue())

    for _ in range(15):
        msg_type, data = await ws.receive_timeout(2000)
        if data is None:
            print(f"[{state['label']}] join: connection closed"); return False
        if msg_type == 255:
            continue
        if msg_type == 3 and data and len(data) >= 3 and data[0] == 0xe2:
            rc = read_short_le(data, 1)
            if rc != 0:
                print(f"[{state['label']}] join fail rc={rc} {extract_debug_message(data)}")
                return False
            state["gs_token"] = parse_simple_string(data, 221)
            gs_addr = parse_simple_string(data, 230)
            if not gs_addr:
                state["room_name"] = name
                return True
            await ws.aclose()
            state["master_ws"] = None
            if not await connect_to_game_server(state, gs_addr):
                print(f"[{state['label']}] GS connect failed")
                return False
            gs_buf = io.BytesIO()
            gs_buf.write(bytes([0xe2, 0x02]))
            gs_buf.write(b'\xff\x07'); raw2 = name.encode(); write_varint(gs_buf, len(raw2)); gs_buf.write(raw2)
            gs_buf.write(bytes([0xe8, 0x1c]))  # CheckUserOnJoin = true
            await state["master_ws"].send_operation(gs_buf.getvalue())
            joined = False
            for _ in range(20):
                gt, gd = await state["master_ws"].receive_timeout(4000)
                if gd is None:
                    break
                if gt == 255:
                    continue
                if gt == 2 and gd and len(gd) >= 2:
                    if gd[0] == 255:
                        joined = True; break
                    continue
                if gt == 3 and gd and len(gd) >= 3 and gd[0] == 0xe2:
                    gs_rc = read_short_le(gd, 1)
                    if gs_rc == 0:
                        joined = True; break
                    print(f"[{state['label']}] GS join fail rc={gs_rc} {extract_debug_message(gd)}")
                    return False
                if gt == 5:
                    print(f"[{state['label']}] disc: {extract_debug_message_at(gd,2)}"); return False
            if not joined:
                print(f"[{state['label']}] join timeout"); return False
            state["on_game_server"] = True
            state["room_name"] = name
            # Старые фоновые задачи уже остановлены в join_all_bots, но на всякий случай перезапустим
            await _stop_bot_background_tasks(state)
            _start_bot_background_tasks(state)
            return True
        if msg_type == 5:
            print(f"[{state['label']}] disc: {extract_debug_message_at(data,2)}"); return False
    print(f"[{state['label']}] join timeout")
    return False


async def join_all_bots(name: str) -> int:
    """Присоединяет всех созданных ботов к одной комнате. Возвращает число успешно вошедших."""
    if not bots:
        print("No bots created. Use 'CreateClients N' first."); return 0

    sem = asyncio.Semaphore(BOT_LOGIN_CONCURRENCY)

    async def _worker(bid, bstate):
        async with sem:
            if not bstate.get("ready"):
                print(f"[bot{bid}] never logged in successfully, skipping (re-run CreateClients for it)")
                return
            # [FIX] Останавливаем текущие фоновые задачи (если есть)
            await _stop_bot_background_tasks(bstate)
            # [FIX] Убеждаемся, что соединение живо
            if not await _ensure_bot_connected(bstate):
                print(f"[bot{bid}] reconnect failed, skipping")
                return
            # Если бот уже был в комнате – выходим из неё
            if bstate.get("on_game_server"):
                if bstate.get("master_ws"):
                    await bstate["master_ws"].aclose()
                    bstate["master_ws"] = None
                bstate["on_game_server"] = False
                # После выхода из комнаты нужно снова войти в лобби (уже переподключены через _ensure_bot_connected)
            # Теперь пытаемся присоединиться к комнате
            ok = await bot_join_room(bstate, name)
            print(f"[bot{bid}] {'joined' if ok else 'FAILED to join'} room '{name}'")

    await asyncio.gather(*(_worker(bid, bstate) for bid, bstate in bots.items()))
    in_room = sum(1 for b in bots.values() if b.get("on_game_server"))
    print(f"{in_room}/{len(bots)} bots are now in room '{name}'.")
    return in_room


async def close_clients() -> None:
    """Отключает и удаляет всех ботов."""
    for bid, bstate in list(bots.items()):
        await _stop_bot_background_tasks(bstate)
        if bstate.get("master_ws"):
            try:
                await bstate["master_ws"].aclose()
            except Exception:
                pass
        bstate["master_ws"] = None
    n = len(bots)
    bots.clear()
    print(f"Closed {n} bot client(s).")


def list_bots() -> None:
    if not bots:
        print("No bots created."); return
    ok = 0
    for bid, bstate in sorted(bots.items()):
        if bstate.get("on_game_server"):
            status = f"in room '{bstate['room_name']}'"
        elif bstate.get("master_ws"):
            status = "in lobby"
        elif bstate.get("ready"):
            status = "disconnected (was ready)"
        else:
            status = "never logged in (failed)"
        if bstate.get("ready"):
            ok += 1
        print(f"  bot{bid}  pfid={bstate.get('playfab_id')}  {status}")
    print(f"  {ok}/{len(bots)} bots successfully logged in at some point.")


async def retry_failed_clients() -> None:
    """Повторяет логин для ботов, у которых ready=False (например, после серии 429)."""
    failed_ids = [bid for bid, b in bots.items() if not b.get("ready")]
    if not failed_ids:
        print("No failed bots to retry."); return
    print(f"Retrying {len(failed_ids)} failed bot(s)...")
    sem = asyncio.Semaphore(BOT_LOGIN_CONCURRENCY)

    async def _worker(bid):
        async with sem:
            bots[bid] = await _bot_login_and_lobby(bid)

    await asyncio.gather(*(_worker(bid) for bid in failed_ids))
    ok = sum(1 for bid in failed_ids if bots[bid].get("ready"))
    print(f"Retry done: {ok}/{len(failed_ids)} now ready.")


def build_raise_event_payload(code: int, data_val=None) -> bytes:
    """OpRaiseEvent (253) — кастомное событие для триггера тестового поведения на сервере
    (например, обработчик коллизий/RPC-заглушка, которую вы реализуете в своём Photon-плагине).
    code: код события 0-255, data_val: простое значение (int/str/bool) или None."""
    buf = io.BytesIO()
    param_count = 2 if data_val is not None else 1
    buf.write(bytes([0xfd, param_count]))   # op 253 RaiseEvent
    buf.write(bytes([0xf4, 0x03, code & 0xFF]))  # key 244 EventCode (byte)
    if data_val is not None:
        buf.write(bytes([0xf5]))  # key 245 Data
        _write_value(buf, data_val)
    return buf.getvalue()


# ════════════════════════════════════════════════════════════════
#  RPC helpers — чат
# ════════════════════════════════════════════════════════════════

def _read_typed_value_at(data: bytes, p: list):
    """Read one typed value from data at position p[0] (GpBinaryV18)."""
    if p[0] >= len(data):
        return None
    t = data[p[0]]; p[0] += 1
    if t == 8:   return None
    if t == 27:  return False
    if t == 28:  return True
    if t == 29:  return 0
    if t == 30:  return 0
    if t == 31:  return 0
    if t == 32:  return 0.0
    if t == 33:  return 0.0
    if t == 34:  return 0
    if t == 3:
        if p[0] >= len(data): return None
        v = data[p[0]]; p[0] += 1; return v
    if t == 4:
        if p[0] + 2 > len(data): return None
        v = (data[p[0]] << 8) | data[p[0]+1]; p[0] += 2; return v
    if t == 5:
        import struct
        if p[0] + 4 > len(data): return None
        v = struct.unpack('>f', data[p[0]:p[0]+4])[0]; p[0] += 4; return v
    if t == 6:
        import struct
        if p[0] + 8 > len(data): return None
        v = struct.unpack('>d', data[p[0]:p[0]+8])[0]; p[0] += 8; return v
    if t == 7:
        if p[0] >= len(data): return None
        l = read_varint(data, p)
        if p[0] + l > len(data): return None
        s = data[p[0]:p[0]+l].decode(errors='replace'); p[0] += l; return s
    if t == 9:
        return read_varint(data, p)
    if t == 10:
        v = 0; shift = 0
        while True:
            if p[0] >= len(data): return None
            b = data[p[0]]; p[0] += 1
            v |= (b & 0x7F) << shift; shift += 7
            if not (b & 0x80): break
        return (v >> 1) ^ (-(v & 1))
    if t == 11:
        if p[0] >= len(data): return None
        v = data[p[0]]; p[0] += 1; return v
    if t == 12:
        if p[0] >= len(data): return None
        v = -data[p[0]]; p[0] += 1; return v
    if t == 13:
        if p[0] + 2 > len(data): return None
        v = (data[p[0]] << 8) | data[p[0]+1]; p[0] += 2; return v
    if t == 14:
        if p[0] + 2 > len(data): return None
        v = -((data[p[0]] << 8) | data[p[0]+1]); p[0] += 2; return v
    if t == 21:
        return _read_hashtable_at(data, p)
    if t == 23:
        return _read_object_array_at(data, p)
    if t in (67, 120):
        l = read_varint(data, p)
        if p[0] + l > len(data): return None
        v = data[p[0]:p[0]+l]; p[0] += l; return v
    if t == 0x13:  # full custom type
        if p[0] >= len(data): return None
        p[0] += 1  # skip type code
        l = read_varint(data, p)
        if p[0] + l > len(data): return None
        v = data[p[0]:p[0]+l]; p[0] += l; return v
    if t >= 0x80:  # slim custom type (code = t - 128)
        l = read_varint(data, p)
        if p[0] + l > len(data): return None
        v = data[p[0]:p[0]+l]; p[0] += l; return v
    read_skip_value(data, p, t)
    return None


def read_skip_value(data: bytes, p: list, t: int) -> None:
    if p[0] >= len(data): return
    if t in (3, 34, 11, 12):         p[0] += 1
    elif t in (4, 13, 14):           p[0] += 2
    elif t == 5:                     p[0] += 4
    elif t == 6:                     p[0] += 8
    elif t in (9, 10):               read_varint(data, p)
    elif t == 7:
        l = read_varint(data, p); p[0] += l
    elif t in (67, 120):
        l = read_varint(data, p); p[0] += l
    elif t == 21:
        c = read_varint(data, p)
        for _ in range(c):
            if p[0] >= len(data): break
            kt = data[p[0]]; p[0] += 1; read_skip_value(data, p, kt)
            if p[0] >= len(data): break
            vt = data[p[0]]; p[0] += 1; read_skip_value(data, p, vt)
    elif t == 23:
        c = read_varint(data, p)
        for _ in range(c):
            if p[0] >= len(data): break
            et = data[p[0]]; p[0] += 1; read_skip_value(data, p, et)
    elif t in (20, 104):
        c = read_varint(data, p)
        for _ in range(c):
            if p[0] >= len(data): break
            kt = data[p[0]]; p[0] += 1; read_skip_value(data, p, kt)
            if p[0] >= len(data): break
            vt = data[p[0]]; p[0] += 1; read_skip_value(data, p, vt)
    elif t == 0x13:
        if p[0] >= len(data): return
        p[0] += 1  # skip type code
        l = read_varint(data, p); p[0] += l
    elif t >= 0x80:
        l = read_varint(data, p); p[0] += l


def _read_hashtable_at(data: bytes, p: list) -> dict:
    c = read_varint(data, p)
    result = {}
    for _ in range(c):
        if p[0] >= len(data): break
        k = _read_typed_value_at(data, p)
        if p[0] >= len(data): break
        v = _read_typed_value_at(data, p)
        if k is not None:
            result[k] = v
    return result


def _read_object_array_at(data: bytes, p: list) -> list:
    c = read_varint(data, p)
    result = []
    for _ in range(c):
        if p[0] >= len(data): break
        v = _read_typed_value_at(data, p)
        result.append(v)
    return result


def parse_event_data(data: bytes) -> dict:
    """Parse a GpBinaryV18 EventData packet.
    Returns dict with keys 'code' (int) and 'params' (dict of key->value).
    """
    if not data or len(data) < 2:
        return {}
    code = data[0]
    param_count = data[1]
    p = [2]
    params = {}
    for _ in range(param_count):
        if p[0] + 2 > len(data): break
        key = data[p[0]]; p[0] += 1
        val = _read_typed_value_at(data, p)
        params[key] = val
    return {"code": code, "params": params}


def parse_rpc_info(ev_data: dict) -> dict:
    """Extract RPC info from a parsed RPC event (code=200)."""
    if ev_data.get("code") != 200:
        return {}
    params = ev_data.get("params", {})
    rpc_ht = params.get(245)
    if not isinstance(rpc_ht, dict):
        return {}
    result = {}
    result["view_id"] = rpc_ht.get(0)
    result["prefix"] = rpc_ht.get(1, 0)
    result["timestamp"] = rpc_ht.get(2)
    # method: key 3 = string name, key 5 = shortcut index (byte)
    result["method"] = rpc_ht.get(3)
    result["shortcut"] = rpc_ht.get(5)
    result["rpc_params"] = rpc_ht.get(4)
    result["sender"] = params.get(254)
    return result


def build_rpc_raise_event_payload(view_id: int, method_name: str, *params) -> bytes:
    """Build a RaiseEvent operation (op 253) for a PUN RPC call.
    Matches Photon RpcTarget.All: event code 200 (PunEvent.RPC),
    receivers = Others (server default, key 246 omitted)."""
    ts = int(time.time() * 1000)
    rpc_entries = [
        (bytes([0]), view_id),
        (bytes([2]), ts),
        (bytes([3]), method_name),
    ]
    if params:
        rpc_entries.append((bytes([4]), list(params)))
    ht_bytes = io.BytesIO()
    write_hashtable_raw(ht_bytes, rpc_entries)
    op_buf = io.BytesIO()
    op_buf.write(bytes([0xfd, 0x02]))          # op 253 RaiseEvent, 2 params (no ReceiverGroup)
    op_buf.write(bytes([0xf4, 0x03, 200]))     # key 244 = event code 200 (byte)
    op_buf.write(b'\xf5')                      # key 245 = Data
    op_buf.write(ht_bytes.getvalue())           # RPC Hashtable
    # key 246 (ReceiverGroup) omitted — server defaults to Others, same as RpcTarget.All
    return op_buf.getvalue()


def build_rpc_raise_event_payload_ex(view_id: int, method_name: str, params_list: list | None = None, receiver_group: int | None = None) -> bytes:
    """Build RPC RaiseEvent with optional ReceiverGroup.
    receiver_group: None=default(Others), 0=Others, 1=All, 2=MasterClient"""
    ts = int(time.time() * 1000)
    rpc_entries = [
        (bytes([0]), view_id),
        (bytes([2]), ts),
        (bytes([3]), method_name),
    ]
    if params_list is not None:
        rpc_entries.append((bytes([4]), list(params_list)))
    ht_bytes = io.BytesIO()
    write_hashtable_raw(ht_bytes, rpc_entries)
    param_count = 2
    if receiver_group is not None:
        param_count += 1
    op_buf = io.BytesIO()
    op_buf.write(bytes([0xfd, param_count]))
    op_buf.write(bytes([0xf4, 0x03, 200]))
    op_buf.write(b'\xf5')
    op_buf.write(ht_bytes.getvalue())
    if receiver_group is not None:
        op_buf.write(bytes([0xf6, 0x03, receiver_group & 0xFF]))
    return op_buf.getvalue()



def build_kick_payload(actor_nr: int) -> bytes:
    """PUN CloseConnection: RaiseEvent 203, data = actor, адресат 252 = [actor]."""
    return build_op(253, (244, 203), (245, int(actor_nr)),
                    (252, [int(actor_nr)]))


PUN_MAX_VIEW_IDS = 1000
SPAWN_SUBID_START = 800


def allocate_spawn_view_id(state: dict, owner_actor: int = 1) -> int:
    """Allocate a view id like the old no-limit loader did."""
    try:
        owner_actor = int(owner_actor)
    except (TypeError, ValueError):
        owner_actor = 1
    if owner_actor < 0:
        owner_actor = 1

    try:
        sub_id = int(state.get("_spawn_subid", SPAWN_SUBID_START)) + 1
    except (TypeError, ValueError):
        sub_id = SPAWN_SUBID_START + 1

    state["_spawn_subid"] = sub_id
    return owner_actor * PUN_MAX_VIEW_IDS + sub_id


def build_freeze_sync_payload(view_id: int, pos: "PhotonVector3", rot: "PhotonQuaternion") -> bytes:
    """Строит событие 206 (OnSerializeReliable) для PhotonView, которое реально
    транслирует isKinematic=True всем клиентам в комнате.

    Событие 202 (Instantiate) с isKinematic в instantiationData создаёт объект,
    но САМО ПО СЕБЕ не замораживает Rigidbody на других клиентах — это делает
    именно этот отдельный view-sync пакет. Без него --freeze не работает,
    даже если isKinematic был передан при спавне (см. /Spawn ... --freeze)."""
    ser_ts = int(time.time() * 1000)
    # Базовый freeze-sync для Prop: localTake + isKinematic.
    # Wire/Monitor-специфичный хвост нельзя слать всем подряд: форма потока
    # должна точно совпадать с реальным OnPhotonSerializeView компонента.
    ser_vd = [view_id, False, None, pos, rot, False, True]
    ser_data = [ser_ts, None, ser_vd]
    ser_buf = io.BytesIO()
    ser_buf.write(bytes([0xfd, 0x02]))
    ser_buf.write(bytes([0xf4, 0x03, 206]))
    ser_buf.write(b'\xf5')
    _write_value(ser_buf, ser_data)
    return ser_buf.getvalue()


# ════════════════════════════════════════════════════════════════


def build_monitor_sync_payload(view_id: int, pos: "PhotonVector3", rot: "PhotonQuaternion",
                               is_kinematic: bool, text: str, color: str | None,
                               cache: int | None = None) -> bytes:
    """Send the full Monitor IPunObservable stream: Prop, WireComponent, then Monitor fields."""
    ser_ts = int(time.time() * 1000)
    ser_vd = [
        view_id,
        False, None, pos, rot,          # PhotonTransformViewClassic payload shape used by freeze-sync
        False, bool(is_kinematic),      # Prop: localTake, isKinematic
        False, 0,                       # WireComponent: signal, connectedIds.Count
        text or "", color or "",       # Monitor: monitorText, color
    ]
    ser_data = [ser_ts, None, ser_vd]
    ser_buf = io.BytesIO()
    param_count = 3 if cache is not None else 2
    ser_buf.write(bytes([0xfd, param_count]))
    ser_buf.write(bytes([0xf4, 0x03, 206]))
    ser_buf.write(b'\xf5')
    _write_value(ser_buf, ser_data)
    if cache is not None:
        ser_buf.write(bytes([0xf7, 0x03, cache & 0xFF]))
    return ser_buf.getvalue()


def remember_monitor_state(state: dict, view_id: int, pos: "PhotonVector3", rot: "PhotonQuaternion",
                           is_kinematic: bool, text: str, color: str | None) -> None:
    state.setdefault("_monitor_states", {})[view_id] = {
        "pos": pos,
        "rot": rot,
        "is_kinematic": bool(is_kinematic),
        "text": text or "",
        "color": normalize_monitor_color(color),
    }


async def resend_monitor_states(state: dict, joined_actor: int | None = None) -> None:
    ws = state.get("master_ws")
    monitors = state.get("_monitor_states") or {}
    if not ws or not monitors:
        return
    if joined_actor is not None:
        print(f"\nResyncing {len(monitors)} monitor(s) for actor {joined_actor}...", flush=True)
    # Small stagger: keep Photon send buffer from bursting on join.
    await asyncio.sleep(0.25)
    for view_id, mon in list(monitors.items()):
        text = mon["text"]
        if text:
            await ws.send_operation(
                build_rpc_raise_event_payload_ex(
                    view_id, "SetTextWithoutController", [text], receiver_group=1
                )
            )
            await asyncio.sleep(0.05)
        await ws.send_operation(
            build_monitor_sync_payload(
                view_id,
                mon["pos"],
                mon["rot"],
                mon["is_kinematic"],
                text,
                mon["color"],
            )
        )
        await asyncio.sleep(0.05)


def schedule_monitor_resync(state: dict, joined_actor: int) -> None:
    async def _runner():
        for delay in (0.5, 2.0, 5.0):
            await asyncio.sleep(delay)
            if not state.get("master_ws") or not state.get("on_game_server"):
                return
            await resend_monitor_states(state, joined_actor)
    task = asyncio.ensure_future(_runner())
    state.setdefault("_monitor_resync_tasks", []).append(task)

#  Save-load helpers
# ════════════════════════════════════════════════════════════════

def normalize_save_dict(data: dict | None) -> dict:
    """Normalize save dict keys (Text->text, Color->color, Background color->color)."""
    if not data:
        return {}
    result = {}
    for k, v in data.items():
        lk = k.lower()
        if lk == 'text' and k != 'text' and 'text' not in data:
            result['text'] = v
        elif lk in ('color',) and k.lower() == 'color' and k != 'color' and 'color' not in data:
            result['color'] = v
        elif lk == 'background color' and 'color' not in data:
            result['color'] = v
        else:
            result[k] = v
    return result


def normalize_monitor_color(value) -> str | None:
    """Convert save/controller color values to the format Monitor expects."""
    if value is None:
        return None
    color = str(value).strip()
    if not color:
        return None
    named = {
        "red": "#ff3333",
        "green": "#33ff66",
        "blue": "#3399ff",
        "yellow": "#ffff33",
        "black": "#000000",
        "white": "#ffffff",
    }
    lower = color.lower()
    if lower in named:
        return named[lower]
    if color.startswith('#'):
        return color
    hex_digits = color.lower()
    if len(hex_digits) in (3, 4, 6, 8) and all(ch in '0123456789abcdef' for ch in hex_digits):
        return '#' + color
    return color


def _copy_first_value(data: dict, target_key: str, *source_keys: str) -> None:
    if not isinstance(data, dict) or target_key in data:
        return
    for key in source_keys:
        if key in data:
            data[target_key] = data[key]
            return


def _normalize_prop_data(prop_name: str, inst: dict, rt: dict) -> None:
    nm = (prop_name or "").lower()
    if nm in ("monitor", "pcmonitor", "oldmonitor"):
        _copy_first_value(inst, "text", "text", "Text")
        _copy_first_value(inst, "color", "color", "Color", "Background color")
        _copy_first_value(rt, "text", "text", "Text")
        _copy_first_value(rt, "color", "color", "Color", "Background color")
        return

    if nm == "monitorcontroller":
        _copy_first_value(inst, "text", "text", "Text")
        _copy_first_value(inst, "color", "color", "Color", "Background color")
        _copy_first_value(rt, "text", "text", "Text")
        _copy_first_value(rt, "color", "color", "Color", "Background color")
        return

    if nm == "button":
        _copy_first_value(inst, "toggle", "toggle", "Toggle")
        _copy_first_value(rt, "signal", "signal", "Signal", "toggle", "Toggle")
        if "toggle" not in inst:
            inst["toggle"] = False
        return

    if nm == "timer":
        _copy_first_value(inst, "timeDelay", "timeDelay", "Time", "time")
        if "timeDelay" not in inst:
            inst["timeDelay"] = 1.0
        return


def _resolve_unique_id(ref, unique_id_to_view_id: dict) -> int | None:
    if ref is None:
        return None
    if isinstance(ref, bool):
        return None
    if isinstance(ref, int):
        if ref in unique_id_to_view_id:
            return unique_id_to_view_id[ref]
        ref = float(ref)
    elif isinstance(ref, float):
        pass
    else:
        try:
            ref = float(ref)
        except (TypeError, ValueError):
            return None
    return unique_id_to_view_id.get(ref)


async def load_save_from_file(state: dict, filepath: str, wait_confirm: bool = True) -> None:
    """Load a .svn save file and spawn all props in the current room."""
    if not os.path.exists(filepath):
        filepath2 = filepath + '.svn' if not filepath.endswith('.svn') else filepath
        if not os.path.exists(filepath2):
            print(f"Save file not found: {filepath}")
            return
        filepath = filepath2
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            save_data = json.load(f)
    except Exception as ex:
        print(f"Error reading save file: {ex}")
        return

    props = save_data.get("props", [])
    if not props:
        print("No props in save file")
        return

    map_name = save_data.get("map", "")
    if map_name:
        payload = build_set_properties_payload({"Map": map_name})
        if state.get("master_ws"):
            await state["master_ws"].send_operation(payload)
        print(f"Map set to: {map_name}")

    print(f"Loading {len(props)} props...")
    total = len(props)

    my_actor = state.get("actor_nr", 1)
    other_players = [a for a in state.get("players", {}) if a != my_actor and a != str(my_actor)]
    use_rpc = bool(other_players) or my_actor != 1
    if use_rpc:
        print(f"  Mode: RPC (other players in room, we are not MasterClient)")
    else:
        print(f"  Mode: Event 202 (we are MasterClient, no other players)")

    unique_id_to_view_id: dict[float, int] = {}
    pending_connections: list[tuple[int, list]] = []
    pending_signals: list[tuple[int, bool]] = []
    pending_monitors: list[tuple[int, str, str | None, PhotonVector3, PhotonQuaternion, bool, str]] = []

    for idx, p in enumerate(props):
        pname = p.get("name", "")
        if not pname:
            print(f"  [{idx+1}/{total}] SKIP (no name)")
            continue

        pos = p.get("position", {})
        rot = p.get("rotation", {})
        pv3 = PhotonVector3(pos.get("x", 0), pos.get("y", 0), pos.get("z", 0))
        pquat = PhotonQuaternion(
            rot.get("x", 0), rot.get("y", 0),
            rot.get("z", 0), rot.get("w", 1)
        )
        unique_id = p.get("uniqueId")
        is_kin = p.get("isKinematic", False)
        inst = normalize_save_dict(p.get("instantiationData") or {})
        rt = normalize_save_dict(p.get("runtimeData") or {})
        _normalize_prop_data(pname, inst, rt)
        text = rt.get("text") or inst.get("text")
        color = normalize_monitor_color(rt.get("color") or inst.get("color"))
        connected_refs = rt.get("connectedIds") or rt.get("ConnectedIds") or []

        view_id = None
        if unique_id is not None:
            try:
                unique_id = float(unique_id)
            except (TypeError, ValueError):
                unique_id = None
        ts = int(time.time() * 1000)
        nm = pname.lower()
        if nm == "monitorcontroller":
            inst.setdefault("text", str(text or ""))
            inst.setdefault("color", str(color or ""))
        if use_rpc:
            rpc_params = [pname, pv3, pquat, bool(is_kin), [PhotonDictionaryStringObject(inst)]]
            payload = build_rpc_raise_event_payload_ex(
                1,
                "SpawnObjectMaster",
                rpc_params,
                receiver_group=2,
            )
        else:
            view_id = allocate_spawn_view_id(state, 1)
            entries = [
                (bytes([0]), pname),
                (bytes([1]), pv3),
                (bytes([2]), pquat),
                (bytes([6]), ts),
                (bytes([7]), view_id),
            ]
            if inst:
                entries.append((bytes([5]), [PhotonDictionaryStringObject(inst)]))
            ht = io.BytesIO()
            write_hashtable_raw(ht, entries)
            ht_bytes = ht.getvalue()
            payload = io.BytesIO()
            payload.write(bytes([0xfd, 0x03]))
            payload.write(bytes([0xf4, 0x03, 202]))
            payload.write(b'\xf5')
            payload.write(ht_bytes)
            payload.write(bytes([0xf7, 0x03, 0x05]))
            payload = payload.getvalue()

        if view_id is not None and unique_id is not None:
            unique_id_to_view_id[unique_id] = view_id

        if state.get("master_ws"):
            await state["master_ws"].send_operation(payload)
        print(f"  [{idx+1}/{total}] {pname}")

        # Для direct Event202 view_id известен сразу. Для RPC ждём echo/instantiate event.
        if view_id is not None:
            state.setdefault("_spawned_viewids", {})[idx] = view_id
        if connected_refs:
            pending_connections.append((idx, list(connected_refs)))
        if "signal" in rt:
            pending_signals.append((idx, bool(rt.get("signal"))))
        if is_kin and view_id is not None and state.get("master_ws"):
            await state["master_ws"].send_operation(build_freeze_sync_payload(view_id, pv3, pquat))

        if nm in ("monitor", "pcmonitor", "oldmonitor"):
            mtext = rt.get("text") or inst.get("text") or ""
            mcolor = normalize_monitor_color(rt.get("color") or inst.get("color"))
            pending_monitors.append((idx, str(mtext), mcolor, pv3, pquat, bool(is_kin), nm))

        await asyncio.sleep(0.05)

    if wait_confirm:
        print("Waiting for spawn confirmations...", end="", flush=True)
        for _ in range(30):
            have = len(state.get("_spawned_viewids", {}))
            if have >= total:
                print(f" {have}/{total}")
                break
            print(".", end="", flush=True)
            await asyncio.sleep(1)
        else:
            print(f" {len(state.get('_spawned_viewids', {}))}/{total} (some may be missing)")

    spawned = state.get("_spawned_viewids", {})
    # Let objects fully initialize on remote clients before sending Connect RPCs
    if pending_connections:
        await asyncio.sleep(0.5)
    for save_idx, connected_refs in pending_connections:
        src_vid = spawned.get(save_idx)
        if not src_vid:
            continue
        seen_targets: set[int] = set()
        for ref in connected_refs:
            tgt_vid = _resolve_unique_id(ref, unique_id_to_view_id)
            if not tgt_vid or tgt_vid == src_vid or tgt_vid in seen_targets:
                continue
            seen_targets.add(tgt_vid)
            if state.get("master_ws"):
                await state["master_ws"].send_operation(
                    build_rpc_raise_event_payload_ex(
                        src_vid,
                        "ConnectToWireComponent",
                        [tgt_vid, False],
                        receiver_group=1,
                    )
                )
            await asyncio.sleep(0.02)

    for save_idx, signal_value in pending_signals:
        src_vid = spawned.get(save_idx)
        if not src_vid:
            continue
        if state.get("master_ws"):
            await state["master_ws"].send_operation(
                build_rpc_raise_event_payload_ex(
                    src_vid,
                    "SyncSignal",
                    [bool(signal_value)],
                    receiver_group=1,
                )
            )
        await asyncio.sleep(0.02)

    mon_count = 0
    for save_idx, text, color, mpos, mrot, mkin, mtype in pending_monitors:
        if not text and not color:
            continue
        vid = spawned.get(save_idx)
        if vid:
            if mtype in ("monitor", "pcmonitor", "oldmonitor") and text:
                pay = build_rpc_raise_event_payload_ex(
                    vid, "SetTextWithoutController", [text],
                    receiver_group=1
                )
                if state.get("master_ws"):
                    await state["master_ws"].send_operation(pay)
            if mtype in ("monitor", "pcmonitor", "oldmonitor") and state.get("master_ws"):
                remember_monitor_state(state, vid, mpos, mrot, mkin, text, color)
                await state["master_ws"].send_operation(
                    build_monitor_sync_payload(vid, mpos, mrot, mkin, text, color, cache=5)
                )
            mon_count += 1
            print(f"  Monitor view={vid} text='{text[:40]}'")

    print(f"Done. {len(props)} props loaded, {mon_count} monitors configured.")


# ════════════════════════════════════════════════════════════════
#  Main loop
# ════════════════════════════════════════════════════════════════

def short_id(s: str) -> str:
    if not s or len(s) <= 8: return s
    return s[:8] + "..."


async def _check_connection(state: dict) -> bool:
    """Lightweight keepalive; do not drain op/event responses here."""
    ws = state["master_ws"]
    if not ws or not ws._ws:
        return False
    try:
        await ws._ws.send(make_ping())
        return True
    except Exception:
        return False

async def main() -> None:
    global PHOTON_APP_ID, PHOTON_APP_VER, PHOTON_HOST, PHOTON_PORT, PLAYFAB_TITLE_ID

    parser = argparse.ArgumentParser(description="Photon Tool (Hypper 0.5.0.9, UDP)")
    parser.add_argument("--titleid", default=PLAYFAB_TITLE_ID)
    parser.add_argument("--appid",   default=PHOTON_APP_ID)
    parser.add_argument("--host",    default=PHOTON_HOST)
    parser.add_argument("--port",    type=int, default=PHOTON_PORT)
    parser.add_argument("--ver",     default=PHOTON_APP_VER)
    parser.add_argument("--uid",     default=None, help="UserId (32 hex)")
    args = parser.parse_args()
    PLAYFAB_TITLE_ID = args.titleid
    PHOTON_APP_ID    = args.appid
    PHOTON_APP_VER   = args.ver
    PHOTON_HOST, PHOTON_PORT = args.host, args.port

    state["custom_id"] = args.uid or default_uid()
    state["nickname"] = get_config_nickname()

    print("=== Photon Tool (Hypper 0.5.0.9) ===")
    print(f"  Server: {PHOTON_HOST}:{PHOTON_PORT} (UDP)  AppId: {short_id(PHOTON_APP_ID)}")
    print(f"  Version: {PHOTON_APP_VER}  Auth: Custom (HMAC)")
    print(f"  uid: {state['custom_id']}")
    print(f"  Nickname: {state['nickname']}  Config: {CONFIG_PATH}\n")

    if not await playfab_login(state):       return
    if not await get_photon_token(state):    return
    if not await connect_to_name_server(state): return

    # Получаем начальный список комнат и запускаем фоновые задачи
    print("Loading room list... ", end="", flush=True)
    await _ensure_lobby(state)
    print(f"{len(state['room_cache'])} rooms")

    print("Commands: RoomList, CreateRoom <name> [--ttl N], Join <name>, CreateClients <N>, "
          "JoinAll <name>, Bots, CloseClients, help, exit")

    loop = asyncio.get_event_loop()
    lobby_ping_task = None

    async def _lobby_pinger():
        while True:
            await asyncio.sleep(5)
            if state["master_ws"] and state["master_ws"]._ws and not state["on_game_server"]:
                try:
                    await state["master_ws"]._ws.send(make_ping())
                except Exception:
                    pass

    lobby_ping_task = asyncio.ensure_future(_lobby_pinger())

    try:
        while state["running"]:
            # Сливаем накопившиеся события лобби перед вводом
            await _drain_cache(state)
            try:
                line = await loop.run_in_executor(None, lambda: input("> "))
            except (EOFError, KeyboardInterrupt):
                break
            line = line.strip()
            if not line: continue
            parts = line.split()
            cmd = parts[0].lower()

            if cmd in ("exit", "quit"):
                await close_clients()
                state["running"] = False

            elif cmd == "help":
                print("RoomList  - show all rooms")
                print("CreateRoom <name> [--ttl N] - create a room (main client)")
                print("Join <name> - join existing room (main client, opens in-room console)")
                print("leave     - leave current room")
                print("CreateClients <N> - spawn N bot clients (PlayFab login + Photon auth + lobby)")
                print("JoinAll <name>    - join ALL bot clients to one room (background, no console)")
                print("SetNickname <name> - set lobby nickname and save it to config.json")
                print("Bots      - list bot clients and their status")
                print("RetryClients - retry login for bots that failed (e.g. after 429s)")
                print("CloseClients - disconnect and remove all bot clients")
                print("help      - this")
                print("exit      - quit (also closes all bot clients)")

            elif cmd in ("roomlist", "rl"):
                if not state["master_ws"]:
                    print("Not connected"); continue
                await interactive_room_list(state)

            elif cmd == "leave":
                if state["on_game_server"] and state["master_ws"]:
                    print("Leaving room...")
                    await state["master_ws"].aclose()
                    state["master_ws"] = None; state["on_game_server"] = False
                    if not await connect_to_name_server(state):
                        print("reconnect failed")
                    # Кеш не сбрасываем — _drain_cache обновит через GameList/GameListUpdate
                else:
                    print("Not in a room")

            elif cmd in ("createroom", "cr"):
                if not state["master_ws"]:
                    print("Not connected"); continue
                # Собираем имя комнаты из всех non-flag аргументов
                room_name = "Room"
                create_ttl = 0
                name_parts = []
                i = 1
                while i < len(parts):
                    if parts[i] == "--ttl" and i + 1 < len(parts):
                        i += 1
                        try: create_ttl = int(parts[i])
                        except ValueError: pass
                    else:
                        name_parts.append(parts[i])
                    i += 1
                if name_parts:
                    room_name = " ".join(name_parts)
                if state["on_game_server"]:
                    print("Reconnecting to lobby...")
                    await state["master_ws"].aclose()
                    state["master_ws"] = None; state["on_game_server"] = False
                    if not await connect_to_name_server(state): continue
                    # Кеш не сбрасываем — _drain_cache обновит
                # Проверка: если соединение "молчит", переподключаемся
                if not await _check_connection(state):
                    print("Connection stale, reconnecting...")
                    await state["master_ws"].aclose()
                    state["master_ws"] = None
                    if not await connect_to_name_server(state): continue
                await create_room(state, room_name, create_ttl)

            elif cmd in ("join", "j"):
                if not state["master_ws"]:
                    print("Not connected"); continue
                room_name = " ".join(parts[1:]) if len(parts) > 1 else ""
                if not room_name:
                    print("Usage: join <room_name>"); continue
                if state["on_game_server"]:
                    print("Reconnecting to lobby...")
                    await state["master_ws"].aclose()
                    state["master_ws"] = None; state["on_game_server"] = False
                    if not await connect_to_name_server(state): continue
                if not await _check_connection(state):
                    print("Connection stale, reconnecting...")
                    await state["master_ws"].aclose()
                    state["master_ws"] = None
                    if not await connect_to_name_server(state): continue
                await join_room(state, room_name)

            elif cmd == "createclients":
                if len(parts) < 2:
                    print("Usage: CreateClients <N>"); continue
                try:
                    n = int(parts[1])
                except ValueError:
                    print("N must be an integer"); continue
                await create_clients(n)

            elif cmd == "joinall":
                room_name = " ".join(parts[1:]) if len(parts) > 1 else ""
                if not room_name:
                    print("Usage: JoinAll <room_name>"); continue
                await join_all_bots(room_name)

            elif cmd == "bots":
                list_bots()

            elif cmd == "retryclients":
                await retry_failed_clients()

            elif cmd == "closeclients":
                await close_clients()

            elif cmd == "setnickname" or cmd.startswith("setnickname "):
                nick = line[len("setnickname"):].strip() if cmd == "setnickname" else ""
                if not nick and len(parts) >= 2:
                    nick = parts[1]
                if not nick:
                    print("Usage: SetNickname <name>"); continue
                state["nickname"] = nick
                save_config_nickname(nick)
                print(f"Lobby nickname saved to config.json: '{nick}' (will be sent on next Join/CreateRoom)")
                actor_nr = state.get("actor_nr")
                if actor_nr and state.get("on_game_server") and state.get("master_ws"):
                    ht = io.BytesIO()
                    write_hashtable_raw(ht, [(bytes([255]), nick), ("NickName", nick)])
                    ht_bytes = ht.getvalue()
                    buf = io.BytesIO()
                    buf.write(bytes([0xfc, 0x03]))
                    buf.write(bytes([0xfb])); buf.write(ht_bytes)    # key 251
                    buf.write(bytes([0xfe])); _write_value(buf, actor_nr)  # key 254 = ActorNr
                    buf.write(bytes([0xfa, 0x1c]))                  # key 250 = Broadcast true
                    await state["master_ws"].send_operation(buf.getvalue())
                    print(f"  + Sent SetProperties to GS too")

            else:
                print("Unknown. Try 'help'")
    finally:
        if lobby_ping_task:
            lobby_ping_task.cancel()
            try: await lobby_ping_task
            except asyncio.CancelledError: pass
        await close_clients()
        if state["master_ws"]:
            await state["master_ws"].aclose()


if __name__ == "__main__":
    asyncio.run(main())
