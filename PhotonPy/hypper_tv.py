"""hypper_tv.py - автономный клиент: стена мониторов с видео в Hypper.

Один файл, без соседних модулей. Запуск:
    python hypper_tv.py --room HypperTV --cols 14 --rows 10 --url "..."

Внутри: Photon 0.5.0.9 (UDP, фрагментация, ретрансмит), протокол/билдеры,
спавн мониторов и поток yt-dlp -> ffmpeg -> кадры на стену.
"""
import base64
import sys
import types
import zlib

_PACKED = {
    "photon0509": "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",
    "ptWorkFreeze": "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",
}

for _name, _blob in _PACKED.items():
    _mod = types.ModuleType(_name)
    _mod.__file__ = __file__
    sys.modules[_name] = _mod
    exec(compile(zlib.decompress(base64.b64decode(_blob)).decode("utf-8"),
                 _name + ".py", "exec"), _mod.__dict__)

# ---- основной сценарий (бывший monitor_video.py) ----
#!/usr/bin/env python3
"""monitor_video.py - видео на стене из настоящих пропов `Monitor`.

Один монитор = один объект в комнате (лимит 1000 объектов, у нас 1 объект
на монитор: текст гоняем напрямую через OnSerialize, без Timer/MonitorController).

Геометрия стены взята из Optimized.py: шаг между мониторами 1.73 x 1.06
(экран монитора 650x384 px при scale 0.0025 = 1.625 x 0.96 world units).

Сетка пикселей на монитор: <size=N%> масштабирует текст.
  136% -> 6 колонок, 100% -> 8, 50% -> 12 (калибровка белой рамкой).
Каждый монитор показывает СВОЙ кусок кадра, поэтому стена не требует
"растягивания" одного монитора.

Пример (стена 2x2, 12x8 пикселей на монитор = 24x16 всего):
  ffmpeg -i video.mp4 -an -vf "scale=24:16:flags=neighbor,fps=4" \
         -f rawvideo -pix_fmt rgb24 monitor_24x16.rgb
  python monitor_video.py --room Wall1 --cols 2 --rows 2 --w 12 --h 8 \
         --size 50 --fps 4 --password 1234 --rgb ../video/monitor_24x16.rgb

Калибровка (вместо видео):
  python monitor_video.py --room Cal1 --pattern --cycle "12x8@50,13x8@50,12x9@50"
"""
import argparse
import zlib
import asyncio
import json
import os
import re
import sys
import time

import photon0509 as ph
import ptWorkFreeze as pt

MON_W = 1.73   # шаг мониторов по X (из Optimized.py)
MON_H = 1.06   # шаг по Y
MON_ROT = (0.0, 1.0, 0.0, 0.0)   # монитор повёрнут на 180° по Y


def frame_text(frame: bytes, w: int, h: int, size: int, fw: int, fh: int,
               ox: int = 0, oy: int = 0) -> str:
    """Кусок RGB24-кадра (fw x fh) -> rich-text из блоков █ (h строк по w)."""
    # Как cell_text_from_frame в Android: Monitor зеркалит текст по X и
    # переворачивает по Y, поэтому кадр заранее отражаем. Цвета RLE.
    wall_w, wall_h = max(1, fw), max(1, fh)
    out = [f"<size={size}%><b>"]
    for y in range(h):
        sy = min(oy + (h - 1 - y), wall_h - 1)
        x = 0
        while x < w:
            gx = min(ox + (w - 1 - x), wall_w - 1)
            i = (sy * wall_w + gx) * 3
            if i + 2 < len(frame):
                r, g, b = frame[i] >> 4, frame[i + 1] >> 4, frame[i + 2] >> 4
            else:
                r = g = b = 0
            x2 = x + 1
            while x2 < w:
                gx2 = min(ox + (w - 1 - x2), wall_w - 1)
                i2 = (sy * wall_w + gx2) * 3
                if not (i2 + 2 < len(frame)
                        and frame[i2] >> 4 == r
                        and frame[i2 + 1] >> 4 == g
                        and frame[i2 + 2] >> 4 == b):
                    break
                x2 += 1
            out.append(f"<color=#{r:X}{g:X}{b:X}>" + "\u2588" * (x2 - x) + "</color>")
            x = x2
        if y + 1 < h:
            out.append("\n")
    out.append("</b></size>")
    return "".join(out)


def load_frames(path: str, w: int, h: int) -> list[bytes]:
    data = open(path, "rb").read()
    size = w * h * 3
    if not data:
        return []
    if len(data) % size:
        print(f"warning: {len(data)} not divisible by {size}", flush=True)
    return [data[i:i + size] for i in range(0, len(data) - size + 1, size)]


def pattern_frame(w: int, h: int) -> bytes:
    """Калибровочная сетка: белая рамка + цветной градиент внутри."""
    buf = bytearray()
    for y in range(h):
        for x in range(w):
            border = x in (0, w - 1) or y in (0, h - 1)
            if border:
                buf += bytes([255, 255, 255])
            else:
                buf += bytes([(x * 255) // max(1, w - 1),
                              (y * 255) // max(1, h - 1),
                              60])
    return bytes(buf)


def wall_pos(index: int, cols: int, rows: int, cx: float, cy: float,
             z: float) -> tuple[float, float, float]:
    col = index % cols
    row = index // cols
    x = cx + (col - (cols - 1) / 2.0) * MON_W
    y = cy - (row - (rows - 1) / 2.0) * MON_H
    return round(x, 6), round(y, 6), z


async def spawn_wall(st: dict, cols: int, rows: int, cx: float, cy: float,
                     z: float, dz: float = 0.0,
                     spawn_gap: float = 0.25) -> list[int]:
    """Спавнит cols*rows мониторов, возвращает view id по порядку."""
    vids: list[int] = []
    rot = pt.PhotonQuaternion(*MON_ROT)
    for idx in range(cols * rows):
        x, y, zz = wall_pos(idx, cols, rows, cx, cy, z + dz)
        # PUN: view id = actorNr * 1000 + subId; subId 1..999 уникален в комнате.
        st["_spawn_subid"] = idx
        vid = await pt.spawn_monitor(st, pt.PhotonVector3(x, y, zz), rot)
        if not vid:
            print(f"  monitor #{idx} not spawned", flush=True)
            return []
        vids.append(vid)
        print(f"  monitor #{idx} view={vid} at ({x}, {y}, {zz})", flush=True)
        await asyncio.sleep(spawn_gap)
        if st.get("master_ws"):
            await st["master_ws"].drain_acks()
            await st["master_ws"].retransmit()
    return vids


def marker_age(path: str) -> float | None:
    try:
        return time.time() - os.path.getmtime(path)
    except OSError:
        return None


class UrlSource:
    """Живой поток: yt-dlp -> ffmpeg -> raw rgb24 в памяти (без файла на диске).

    Оба процесса запускаются напрямую (без cmd/shell), поток кадров читается
    по мере надобности: медленный читатель -> backpressure -> yt-dlp не качает
    весь ролик вперёд.
    """

    def __init__(self, ytdlp: str, ffmpeg: str, url: str, fmt: str,
                 w: int, h: int, fps: float, deno: str = "",
                 start_sec: float = 0.0):
        self.start_sec = max(0.0, float(start_sec))
        self.ytdlp = ytdlp
        self.ffmpeg = ffmpeg
        self.url = url
        # Локальный файл или прямая ссылка на видео идут в ffmpeg без yt-dlp.
        self.direct = self._resolve_direct(url)
        self.fmt = fmt
        self.formats = []
        for f in [fmt, "18", "bv*[protocol^=m3u8]", "bv*[height<=480][ext=mp4]"]:
            if f not in self.formats:
                self.formats.append(f)
        self.fmt_idx = 0
        # youtube иногда отдаёт "not available" на дефолтном клиенте
        self.clients = ["", "web_embedded", "android"]
        self.client_idx = 0
        self.deno = deno
        self.w = w
        self.h = h
        self.fps = fps
        self.size = w * h * 3
        self.yt = None
        self.ff = None
        self.pump_task = None
        self.drain_tasks = []
        self.err_yt = bytearray()
        self.err_ff = bytearray()

    @staticmethod
    def _resolve_direct(url: str) -> str | None:
        """Путь к локальному файлу или прямой media-URL (ffmpeg читает сам)."""
        from urllib.parse import urlparse, unquote
        u = (url or "").strip()
        if not u:
            return None
        # Windows drive letter (C:\...) is parsed as scheme='c' by urlparse
        if os.name == "nt" and len(u) >= 2 and u[1] == ":" and u[0].isalpha():
            return os.path.abspath(u) if os.path.isfile(u) else None
        p = urlparse(u)
        if p.scheme == "file":
            path = unquote(p.path)
            if os.name == "nt" and path[:1] == "/":
                path = path[1:]
            return path if os.path.isfile(path) else None
        if p.scheme in ("http", "https"):
            ext = os.path.splitext(p.path)[1].lower()
            if ext in (".mp4", ".m4v", ".mkv", ".webm", ".mov", ".avi",
                       ".ts", ".m3u8", ".mpd"):
                return u
            return None
        if os.path.isfile(u):
            return os.path.abspath(u)
        return None

    async def start(self) -> None:
        if self.start_sec > 0:
            print(f"start at {self.start_sec:.0f}s", flush=True)

        if self.direct:
            ff_args = [self.ffmpeg, "-loglevel", "error"]
            if self.start_sec > 0:
                # для файла/URL -ss до -i = быстрый seek без чтения начала
                ff_args += ["-ss", f"{self.start_sec:.2f}"]
            ff_args += ["-i", self.direct,
                        "-vf", f"scale={self.w}:{self.h}:flags=neighbor,fps={self.fps}",
                        "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]
            self.ff = await asyncio.create_subprocess_exec(
                *ff_args,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            self.drain_tasks = [
                asyncio.create_task(self._drain(self.ff.stderr, self.err_ff))]
            print(f"stream started (ffmpeg <- {self.direct})", flush=True)
            return

        yt_args = [self.ytdlp]
        if self.deno and os.path.exists(self.deno):
            yt_args += ["--js-runtimes", f"deno:{self.deno}"]
        client = self.clients[self.client_idx] if self.clients else ""
        if client:
            yt_args += ["--extractor-args", f"youtube:player_client={client}"]
        yt_args += ["-f", self.formats[self.fmt_idx], "--no-part",
                    "-o", "-", self.url]
        self.yt = await asyncio.create_subprocess_exec(
            *yt_args,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        ff_args = [self.ffmpeg, "-loglevel", "error", "-i", "pipe:0"]
        if self.start_sec > 0:
            # на пайпе -ss до -i не работает, поэтому после: ffmpeg
            # отбрасывает начало и отдаёт кадры уже с нужного места
            ff_args += ["-ss", f"{self.start_sec:.2f}"]
        ff_args += ["-vf", f"scale={self.w}:{self.h}:flags=neighbor,fps={self.fps}",
                    "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]
        self.ff = await asyncio.create_subprocess_exec(
            *ff_args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        self.pump_task = asyncio.create_task(self._pump())
        self.drain_tasks = [asyncio.create_task(self._drain(self.ff.stderr, self.err_ff))]
        if self.yt is not None:
            self.drain_tasks.append(
                asyncio.create_task(self._drain(self.yt.stderr, self.err_yt)))
        print("stream started (yt-dlp -> ffmpeg)", flush=True)

    async def _drain(self, stream, buf: bytearray) -> None:
        try:
            while True:
                chunk = await stream.read(4096)
                if not chunk:
                    break
                buf.extend(chunk)
        except Exception:
            pass

    async def _pump(self) -> None:
        if self.yt is None:
            return
        src, dst = self.yt.stdout, self.ff.stdin
        try:
            while True:
                chunk = await src.read(65536)
                if not chunk:
                    break
                dst.write(chunk)
                await dst.drain()
        except Exception:
            pass
        try:
            dst.close()
        except Exception:
            pass

    async def read(self) -> bytes | None:
        try:
            return await self.ff.stdout.readexactly(self.size)
        except Exception:
            e1 = bytes(self.err_yt).decode("utf-8", "replace").strip()
            e2 = bytes(self.err_ff).decode("utf-8", "replace").strip()
            print("stream ended; yt-dlp rc=",
                  self.yt.returncode if self.yt else None, flush=True)
            if e1:
                print("  yt-dlp: " + "\n  ".join(e1.splitlines()[-5:]), flush=True)
            if e2:
                print("  ffmpeg: " + "\n  ".join(e2.splitlines()[-5:]), flush=True)
            return None

    def next_format(self) -> bool:
        if self.direct:
            return False
        if self.fmt_idx + 1 < len(self.formats):
            self.fmt_idx += 1
            print(f"trying next format: {self.formats[self.fmt_idx]}", flush=True)
            return True
        self.fmt_idx = 0
        if self.client_idx + 1 < len(self.clients):
            self.client_idx += 1
            print(f"trying player_client: {self.clients[self.client_idx] or 'default'}",
                  flush=True)
            return True
        return False

    async def stop(self) -> None:
        for task in ([self.pump_task] if self.pump_task else []) + list(self.drain_tasks):
            task.cancel()
        for proc in (self.yt, self.ff):
            try:
                if proc and proc.returncode is None:
                    proc.kill()
                    await proc.wait()
            except Exception:
                pass
        for task in ([self.pump_task] if self.pump_task else []) + list(self.drain_tasks):
            try:
                await task
            except BaseException:
                pass


def parse_cycle(spec: str) -> list[tuple[int, int, int]]:
    out = []
    for part in spec.split(","):
        part = part.strip().lower().replace("х", "x")
        if not part:
            continue
        wh, _, sz = part.partition("@")
        w, h = wh.split("x")
        out.append((int(w), int(h), int(sz or "100")))
    return out


def _default_tool(name: str, rel: str) -> str:
    """Локальный tools/ рядом с проектом, иначе — из PATH."""
    local = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "tools", rel)
    return local if os.path.exists(local) else name


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--room", default="", help="имя комнаты (если пусто — запрос с клавиатуры)")
    ap.add_argument("--raw-name", action="store_true",
                    help="не вырезать теги: --room \"<color=red>HypperTV</color>\"")
    ap.add_argument("--debug-events", action="store_true",
                    help="печатать все входящие события (для отладки чата)")
    ap.add_argument("--vid", default="",
                    help="только ID ролика: --vid EMCtX6_-eQ8")
    ap.add_argument("--url", default="",
                    help="YouTube-ссылка, прямой http(s) mp4/m3u8 или путь к видеофайлу")
    ap.add_argument("--ytdlp", default=_default_tool("yt-dlp", r"yt-dlp\yt-dlp.exe"))
    ap.add_argument("--ffmpeg", default=_default_tool("ffmpeg", r"ffmpeg\bin\ffmpeg.exe"))
    ap.add_argument("--yt-format", default="bv*[vcodec^=avc1][height<=720]")
    ap.add_argument("--deno", default=_default_tool("deno", r"deno\deno.exe"),
                    help="JS-рантайм для yt-dlp")
    ap.add_argument("--loop-stream", action="store_true")
    ap.add_argument("--rgb", default=os.path.join("..", "video", "monitor_24x16.rgb"))
    ap.add_argument("--cols", type=int, default=7, help="мониторов по X")
    ap.add_argument("--rows", type=int, default=5, help="мониторов по Y")
    ap.add_argument("--w", type=int, default=22, help="пикселей на монитор по X")
    ap.add_argument("--h", type=int, default=12, help="пикселей на монитор по Y")
    ap.add_argument("--size", type=int, default=42, help="размер текста в процентах")
    ap.add_argument("--fps", type=float, default=4.0)
    ap.add_argument("--wait-player", type=float, default=0.0)
    ap.add_argument("--seconds", type=float, default=900.0)
    ap.add_argument("--password", default="")
    ap.add_argument("--max", type=int, default=2)
    ap.add_argument("--mode", type=int, default=0, choices=[0, 1, 2],
                    help="GameMode: 0=Free, 1=Private, 2=Adventure")
    ap.add_argument("--max-props", type=int, default=1000,
                    help="лимит предметов в комнате (MaxProps)")
    ap.add_argument("--max-vehicles", type=int, default=40,
                    help="лимит транспорта в комнате (MaxVehicles)")
    ap.add_argument("--pvp", action="store_true", default=False)
    ap.add_argument("--hidden", action="store_true", help="не показывать комнату в лобби")
    ap.add_argument("--closed", action="store_true", help="закрыть вход новым игрокам")
    ap.add_argument("--cx", type=float, default=-2.0, help="центр стены по X")
    ap.add_argument("--cy", type=float, default=None,
                    help="центр стены по Y (по умолчанию: нижний ряд ~0.6 м)")
    ap.add_argument("--cz", type=float, default=15.0)
    ap.add_argument("--spawn-gap-ms", type=float, default=250.0,
                    help="пауза между спавнами мониторов (плотная пачка теряется)")
    ap.add_argument("--ready-sec", type=float, default=20.0,
                    help="сколько ждать выхода игрока с экрана загрузки")
    ap.add_argument("--start-sec", type=float, default=0.0,
                    help="с какой секунды видео начинать")
    ap.add_argument("--refresh", type=float, default=10.0,
                    help="период полного ре-синка плиток, секунды (0 = выкл.)")
    ap.add_argument("--gap-ms", type=float, default=5.0,
                    help="пауза между мониторами в кадре, мс")
    ap.add_argument("--pattern", action="store_true")
    ap.add_argument("--cycle", default="", help="калибровка: 12x8@50,13x8@50,...")
    ap.add_argument("--cycle-period", type=float, default=8.0)
    ap.add_argument("--accept-marker", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "accept.flag"))
    ap.add_argument("--accept-window", type=float, default=30.0)
    ap.add_argument("--accept-any", action="store_true",
                    help="принимать любого вошедшего (для ручного входа игрока)")
    ap.add_argument("--kick", action="store_true",
                    help="выкидывать чужих (по умолчанию выключено)")
    args = ap.parse_args()
    if args.vid:
        # ID надёжнее URL: шелл иногда портит ссылку
        args.url = "https://youtu.be/" + args.vid.strip()
        print(f"video id: {args.vid}", flush=True)
    # имя можно ввести с клавиатуры и вставить прямо из игры вместе с тегами цвета
    if not args.room:
        args.room = input("Room name: ")
    if args.raw_name:
        # имя как есть: <color=red>HypperTV</color> игра отрисует красным
        args.room = args.room.strip().strip('"\'')
    else:
        args.room = re.sub(r"<[^>]*>", "", args.room).strip().strip('"\'').strip()
    print(f"room: {args.room!r}", flush=True)
    if args.url and args.seconds == 900.0:
        args.seconds = 6 * 3600.0      # часовой стрим не должен обрываться через 15 мин

    if args.cy is None:
        cy = 0.6 + (args.rows - 1) * MON_H / 2
        print(f"auto cy={cy:.2f} for {args.rows} rows", flush=True)
    else:
        cy = args.cy

    n_monitors = args.cols * args.rows
    if n_monitors > 990:
        print(f"too many monitors: {n_monitors} (limit 999 per player)", flush=True)
        return 1
    print(f"wall {args.cols}x{args.rows} = {n_monitors} objs, "
          f"{args.cols * MON_W:.1f}x{args.rows * MON_H:.1f} m, "
          f"pixels {args.cols * args.w}x{args.rows * args.h}", flush=True)

    cycle = parse_cycle(args.cycle) if args.cycle else []
    if cycle:
        args.pattern = True
    sw, sh = (cycle[0][0] if cycle else args.w), (cycle[0][1] if cycle else args.h)
    fw, fh = args.cols * sw, args.rows * sh

    frames: list[bytes] = []
    if args.url:
        print(f"source: {args.url}  (ffmpeg, {fw}x{fh} @ {args.fps} fps)",
              flush=True)
    elif not args.pattern:
        frames = load_frames(args.rgb, fw, fh)
        if not frames:
            print(f"no frames in {args.rgb} (нужно {fw}x{fh})")
            return 1
        print(f"frames: {len(frames)} ({len(frames) / args.fps:.1f}s at {args.fps} fps, "
              f"wall {args.cols}x{args.rows} x {args.w}x{args.h} = {fw}x{fh})",
              flush=True)
    elif args.pattern:
        frames = [pattern_frame(fw, fh)]

    st = pt.make_state("pyvideo")
    st["custom_id"] = ph.default_uid()
    st["playfab_id"] = st["custom_id"]
    st["nickname"] = "PyVideo"

    if not await pt.connect_to_name_server(st):
        print("connect failed")
        return 1
    if not await pt.create_room(st, args.room, max_players=args.max,
                               password=args.password, pvp=args.pvp,
                               visible=not args.hidden, open_room=not args.closed,
                               gamemode=args.mode,
                               max_props=args.max_props,
                               max_vehicles=args.max_vehicles):
        return 2

    phone_actor = None
    vids: list[int] = []
    epoch = 0

    async def handle_join(actor: int) -> bool:
        nonlocal phone_actor, vids, epoch
        if args.accept_any:
            if phone_actor != actor:
                phone_actor = actor
                print(f"[{time.strftime('%H:%M:%S')}] accept {actor} (accept-any)",
                      flush=True)
            return True
        if phone_actor is not None:
            if actor == phone_actor:
                return True
            if args.kick:
                await st["master_ws"].send_operation(pt.build_kick_payload(actor))
                print(f"[{time.strftime('%H:%M:%S')}] kick {actor} (мешает)", flush=True)
            return False
        age = marker_age(args.accept_marker)
        if age is not None and 0 <= age <= args.accept_window:
            phone_actor = actor
            print(f"[{time.strftime('%H:%M:%S')}] accept {actor} (метка {age:.1f}s)",
                  flush=True)
            return True
        if args.kick:
            await st["master_ws"].send_operation(pt.build_kick_payload(actor))
            print(f"[{time.strftime('%H:%M:%S')}] kick {actor} "
                  f"(метка {age if age is None else round(age, 1)})", flush=True)
        return False

    def handle_chat(msg_type, data) -> None:
        """Ловим чат игры: RPC PostMassage (событие 200)."""
        if msg_type not in (2, 3, 4) or not data:
            return
        if args.debug_events:
            print(f"[ev {time.strftime('%H:%M:%S')}] type={msg_type} "
                  f"code={data[0] if data else -1} len={len(data)}", flush=True)
        if data[0] != 200:
            return
        try:
            rpc = pt.parse_rpc_info(pt.parse_event_data(data))
            params = rpc.get("rpc_params")
            method = rpc.get("method")
            if args.debug_events:
                print(f"[rpc {time.strftime('%H:%M:%S')}] method={method} "
                      f"sender={rpc.get('sender')} view={rpc.get('view_id')} "
                      f"params={str(params)[:120]}", flush=True)
            is_chat = method == "PostMassage"
            if not is_chat and isinstance(params, (list, tuple)) and len(params) >= 2:
                is_chat = isinstance(params[0], str) and params[1] is True
            if not is_chat or not params:
                return
            sender = rpc.get("sender")
            nick = str(st.get("players", {}).get(str(sender), "")) or f"actor{sender}"
            text = str(params[0])
            print(f"[chat {time.strftime('%H:%M:%S')}] {nick}: {text}", flush=True)
            st.setdefault("chat_log", []).append(text)
        except Exception:
            pass

    async def wait_phone_ready(actor: int, timeout: float) -> bool:
        """Ждём, пока клиент игрока выйдет с экрана загрузки.

        Готовность = событие 202 (Instantiate) от объектов этого игрока
        (view id в его блоке). Всё, что мы отправим раньше, клиент выбрасывает,
        поэтому объекты стены «теряются».
        """
        end = time.time() + max(0.0, timeout)
        last = time.time()
        while time.time() < end:
            msg_type, data = await st["master_ws"].receive_timeout(400)
            handle_chat(msg_type, data)
            if msg_type == 4 and data and data[0] == 202:
                try:
                    params = pt.parse_event_data(data).get("params", {})
                    vid = params.get(7)
                    if isinstance(vid, int) and vid // 1000 == actor:
                        print(f"phone {actor} is in game (view={vid})", flush=True)
                        return True
                except Exception:
                    pass
            elif msg_type == 4 and data and data[0] == 255:
                other = join_actor(msg_type, data)
                if other and other != actor:
                    await handle_join(other)
            if time.time() - last > 3.0:
                try:
                    await st["master_ws"].send_ping()
                except Exception:
                    pass
                last = time.time()
        return False

    def join_actor(msg_type, data) -> int | None:
        if msg_type == 4 and data and data[0] == 255:
            ev = pt.parse_event_data(data)
            params = ev.get("params", {})
            actor = params.get(254)
            if actor and actor != st.get("actor_nr"):
                nick = params.get(255)
                if isinstance(nick, str) and nick:
                    # чтобы в чате было видно ник, а не "actor4"
                    st.setdefault("players", {})[str(actor)] = nick
                    print(f"  player {actor} = {nick!r}", flush=True)
                return actor
        return None

    async def build_wall() -> None:
        nonlocal vids, epoch
        epoch += 1
        print(f"building wall {args.cols}x{args.rows} (epoch {epoch})...", flush=True)
        new_vids = await spawn_wall(st, args.cols, args.rows, args.cx, cy,
                                    args.cz, dz=0.02 * (epoch - 1),
                                    spawn_gap=args.spawn_gap_ms / 1000.0)
        if new_vids:
            vids = new_vids

    print(f"waiting for the phone (up to {args.wait_player}s)...", flush=True)
    deadline = time.time() + max(0.0, args.wait_player)
    last_ping = time.time()
    while time.time() < deadline and not vids:
        msg_type, data = await st["master_ws"].receive_timeout(800)
        handle_chat(msg_type, data)
        actor = join_actor(msg_type, data)
        if actor and await handle_join(actor) and not vids:
            print(f"waiting for player {actor} to finish loading "
                  f"(max {args.ready_sec:.0f}s)...", flush=True)
            ok = await wait_phone_ready(actor, args.ready_sec)
            print("client ready" if ok else "ready timeout, building anyway",
                  flush=True)
            await build_wall()
        elif actor and vids:
            print(f"wall already exists, resending state to {actor}", flush=True)
            await pt.resend_monitor_states(st, actor)
        if time.time() - last_ping > 3.0:
            try:
                await st["master_ws"].send_ping()
            except Exception:
                pass
            last_ping = time.time()

    if not vids:
        print("no player joined, spawning anyway", flush=True)
        await build_wall()
    if not vids:
        return 3

    url_src = None
    if args.url:
        url_src = UrlSource(args.ytdlp, args.ffmpeg, args.url, args.yt_format,
                            args.cols * args.w, args.rows * args.h, args.fps,
                            deno=args.deno, start_sec=args.start_sec)
        await url_src.start()

    period = 1.0 / max(0.5, args.fps)
    end = time.time() + args.seconds
    idx = sent = 0
    if frames:
        idx = int(max(0.0, args.start_sec) * args.fps) % len(frames)
        print(f"start at {args.start_sec:.1f}s -> frame {idx}", flush=True)
    last_ping = time.time()
    t_next = time.time()
    t_start = time.time()
    cycle_idx = -1
    last_text: dict[int, str] = {}
    last_refresh = time.time()
    cycle_t0 = time.time()

    while time.time() < end:
        # ---- выбрать конфиг текста (калибровка или видео) ----
        if cycle:
            ci = int((time.time() - cycle_t0) / args.cycle_period)
            ci %= len(cycle)
            if ci != cycle_idx:
                cycle_idx = ci
                cw, ch, csz = cycle[ci]
                fw_, fh_ = args.cols * cw, args.rows * ch
                frames = [pattern_frame(fw_, fh_)]
                args.w, args.h, args.size = cw, ch, csz
                print(f"[{time.strftime('%H:%M:%S')}] config {cw}x{ch}@{csz}% "
                      f"- кадр {fw_}x{fh_}", flush=True)
        elif cycle_idx < 0:
            cycle_idx = 0

        if url_src is not None:
            frame = await url_src.read()
            if frame is None:
                if url_src.next_format() or args.loop_stream:
                    await url_src.stop()
                    await url_src.start()
                    continue
                print("stream ended", flush=True)
                break
        else:
            frame = frames[idx % len(frames)]
            idx += 1
        if len(last_text) != len(vids):
            last_text.clear()
        if args.refresh > 0 and time.time() - last_refresh > args.refresh:
            last_text.clear()          # периодический полный ре-синк
            last_refresh = time.time()
        fw_, fh_ = args.cols * args.w, args.rows * args.h

        for i, vid in enumerate(vids):
            col, row = i % args.cols, i // args.cols
            text = frame_text(frame, args.w, args.h, args.size, fw_, fh_,
                              ox=col * args.w, oy=row * args.h)
            if last_text.get(i) == text:
                continue
            last_text[i] = text
            x, y, z = wall_pos(i, args.cols, args.rows, args.cx, cy,
                               args.cz + 0.02 * (epoch - 1))
            ok = await st["master_ws"].send_operation(
                pt.build_monitor_sync_payload(vid, pt.PhotonVector3(x, y, z),
                                              pt.PhotonQuaternion(*MON_ROT),
                                              True, text, None, cache=None))
            if i == 0 and sent % 4 == 0:
                print(f"  m0 sent ok={ok} len={len(text)} crc={zlib.crc32(text.encode()) & 0xFFFF}",
                      flush=True)
            if i % 16 == 15:
                # подтверждения + ретрансмит потерянных reliable-команд
                for _mt, _dt in await st["master_ws"].drain_acks():
                    handle_chat(_mt, _dt)
                await st["master_ws"].retransmit()
            if len(vids) > 1 and args.gap_ms > 0:
                await asyncio.sleep(args.gap_ms / 1000.0)
        sent += 1
        for _mt, _dt in await st["master_ws"].drain_acks():
            handle_chat(_mt, _dt)
        await st["master_ws"].retransmit()

        if url_src is None:
            t_next += period
            sleep_for = t_next - time.time()
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)
            else:
                t_next = time.time()

        for _ in range(3):
            msg_type, data = await st["master_ws"].receive_timeout(5)
            handle_chat(msg_type, data)
            actor = join_actor(msg_type, data)
            if actor and await handle_join(actor) and phone_actor == actor:
                print(f"phone {actor} re-joined -> resending state (no new objects)",
                      flush=True)
                await pt.resend_monitor_states(st, actor)
            if not data:
                break
        if time.time() - last_ping > 3.0:
            try:
                await st["master_ws"].send_ping()
            except Exception:
                pass
            last_ping = time.time()

        if sent % max(1, int(args.fps * 5)) == 0:
            if frames:
                print(f"[{time.strftime('%H:%M:%S')}] frame {idx % len(frames)}/{len(frames)}",
                      flush=True)
            else:
                print(f"[{time.strftime('%H:%M:%S')}] stream frames sent: {sent}",
                      flush=True)

    print(f"done, sent {sent} frames")
    # выходим из комнаты явно, иначе на сервере остаётся «призрак» с этим именем
    try:
        await st["master_ws"].send_operation(pt.build_op(228))
        await asyncio.sleep(0.3)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))