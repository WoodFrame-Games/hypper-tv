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
import monitor_test as mt

MON_W = 1.73   # шаг мониторов по X (из Optimized.py)
MON_H = 1.06   # шаг по Y


def frame_text(frame: bytes, w: int, h: int, size: int, fw: int, fh: int,
               ox: int = 0, oy: int = 0) -> str:
    """Кусок RGB24-кадра (fw x fh) -> rich-text из блоков █ (h строк по w)."""
    lines = []
    for y in range(h):
        blocks = []
        base = ((oy + y) * fw + ox) * 3
        for x in range(w):
            i = base + x * 3
            r, g, b = frame[i], frame[i + 1], frame[i + 2]
            blocks.append(f"<color=#{r >> 4:X}{g >> 4:X}{b >> 4:X}>\u2588</color>")
        lines.append("<b>" + "".join(blocks) + "</b>")
    return f"<size={size}%>" + "\n".join(lines) + "</size>"


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
    """Спавнит cols*rows мониторов, возвращает view id по индексу."""
    vids: list[int] = []
    for idx in range(cols * rows):
        x, y, zz = wall_pos(idx, cols, rows, cx, cy, z + dz)
        save = mt.build_save("#000000")
        prop = save["props"][0]
        prop["position"] = {"x": x, "y": y, "z": zz}
        prop["uniqueId"] = mt.unique_id(x, y, zz)
        save["props"] = [prop]

        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_video.svn")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(save, f)

        st["_spawned_viewids"] = {}
        # PUN: view id = actorNr * 1000 + subId. Держимся в блоке своего актёра
        # (1001..1999), иначе объекты уходят в ownership другого игрока.
        owner = st.get("actor_nr") or 1
        # PUN: view id = actorNr * 1000 + subId. Нижние sub (1..500) игра тратит
        # на свои объекты (игрок, сцена), поэтому берём верх блока: 500..999.
        st["_spawn_subid"] = idx
        await pt.load_save_from_file(st, path, wait_confirm=False)
        vid = (st.get("_spawned_viewids") or {}).get(0)
        if not vid:
            print(f"  monitor #{idx} not spawned", flush=True)
            return []
        vids.append(vid)
        print(f"  monitor #{idx} view={vid} at ({x}, {y}, {zz})", flush=True)
        # Пачка instantiate-событий обрабатывается игрой за один Dispatch;
        # если она слишком плотная, диспетчер падает с исключением и остаток
        # объектов теряется. Разносим спавн во времени.
        await asyncio.sleep(spawn_gap)
        # подтверждения и ретрансмит: часть instantiate-событий иначе теряется
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

    async def _direct_url(self) -> str:
        """Прямая ссылка на поток (её ffmpeg умеет искать по времени)."""
        args = [self.ytdlp]
        if self.deno and os.path.exists(self.deno):
            args += ["--js-runtimes", f"deno:{self.deno}"]
        args += ["-f", self.formats[self.fmt_idx], "-g", self.url]
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await proc.communicate()
        for line in out.decode("utf-8", "replace").splitlines():
            if line.startswith("http"):
                return line.strip()
        return ""

    async def start(self) -> None:
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
        if self.start_sec > 0:
            print(f"start at {self.start_sec:.0f}s", flush=True)
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
                    help="YouTube/URL: живой поток через yt-dlp | ffmpeg (без файла)")
    ap.add_argument("--ytdlp", default=r"C:\Work\Hypper\tools\ytdlp\yt-dlp.exe")
    ap.add_argument("--ffmpeg", default=r"C:\Work\Hypper\tools\ffmpeg"
                                       r"\ffmpeg-n8.1-latest-win64-gpl-8.1\bin\ffmpeg.exe")
    ap.add_argument("--yt-format", default="bv*[vcodec^=avc1][height<=720]")
    ap.add_argument("--deno", default=r"C:\Work\Hypper\tools\deno\deno.exe",
                    help="JS-рантайм для yt-dlp")
    ap.add_argument("--loop-stream", action="store_true")
    ap.add_argument("--rgb", default=os.path.join("..", "video", "monitor_24x16.rgb"))
    ap.add_argument("--cols", type=int, default=2, help="мониторов по X")
    ap.add_argument("--rows", type=int, default=2, help="мониторов по Y")
    ap.add_argument("--w", type=int, default=12, help="пикселей на монитор по X")
    ap.add_argument("--h", type=int, default=8, help="пикселей на монитор по Y")
    ap.add_argument("--size", type=int, default=50, help="размер текста в процентах")
    ap.add_argument("--fps", type=float, default=4.0)
    ap.add_argument("--wait-player", type=float, default=300.0)
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
        print(f"source: {args.url}  (yt-dlp -> ffmpeg, {fw}x{fh} @ {args.fps} fps)",
              flush=True)
    elif not args.pattern:
        frames = load_frames(args.rgb, fw, fh)
        if not frames:
            print(f"no frames in {args.rgb} (нужно {fw}x{fh})")
            return 1
        print(f"frames: {len(frames)} ({len(frames) / args.fps:.1f}s at {args.fps} fps, "
              f"wall {args.cols}x{args.rows} x {args.w}x{args.h} = {fw}x{fh})",
              flush=True)

    st = pt.make_state("pyvideo")
    st["custom_id"] = ph.default_uid()
    st["playfab_id"] = st["custom_id"]
    st["nickname"] = "PyVideo"

    if not await pt.connect_to_name_server(st):
        print("connect failed")
        return 1
    if not await mt.enter_room(st, args.room, create=True, max_players=args.max,
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
                                              pt.PhotonQuaternion(*mt.MON_ROT),
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