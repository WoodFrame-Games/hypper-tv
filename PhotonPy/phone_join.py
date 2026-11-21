#!/usr/bin/env python3
"""phone_join.py - автоматический вход с телефона в комнату (adb, по координатам).

Координаты сняты со скриншотов Android 9 / 1520x720 (CPH2083):
  Мультиплеер      (200, 200)
  Сервер Лист      (200, 210)
  поле поиска      (1295, 36)
  ok клавиатуры    (1330, 248)
  первая строка    (600, 160)
  поле пароля      (760, 352)
  Войти            (925, 455)
  Закрыть          (580, 455)

Перед тапом по строке скрипт обновляет файл-метку (accept.flag), чтобы
monitor_video.py принял именно этот вход и не выкинул его как чужого.

Примеры:
  python phone_join.py --room Lock2 --password 1234
  python phone_join.py --room PyVidA --password 1 --no-launch
"""
import argparse
import os
import subprocess
import sys
import time

ADB = r"C:\Users\USER\AppData\Local\Android\Sdk\platform-tools\adb.exe"
PKG = "com.Hypper/com.unity3d.player.UnityPlayerActivity"
ROOT = os.path.dirname(os.path.abspath(__file__))

TAP_MULTIPLAYER = (200, 200)
TAP_SERVER_LIST = (200, 210)
TAP_SEARCH = (1295, 36)
TAP_KEYBOARD_OK = (1330, 248)
TAP_FIRST_ROW = (600, 160)
TAP_PASSWORD_FIELD = (760, 352)
TAP_JOIN = (925, 455)
TAP_CLOSE = (580, 455)


def adb(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([ADB, *args], capture_output=True)


def tap(x: int, y: int, wait: float = 0.0) -> None:
    adb("shell", "input", "tap", str(x), str(y))
    if wait:
        time.sleep(wait)


def key(code: int, count: int = 1, wait: float = 0.0) -> None:
    for _ in range(count):
        adb("shell", "input", "keyevent", str(code))
        time.sleep(0.05)
    if wait:
        time.sleep(wait)


def text(value: str) -> None:
    # adb input text режет строку по пробелам: кодируем их как %s
    adb("shell", "input", "text", value.replace(" ", "%s"))


def shot(path: str) -> None:
    png = subprocess.run([ADB, "exec-out", "screencap", "-p"],
                         capture_output=True).stdout
    with open(path, "wb") as f:
        f.write(png)


def touch_marker(path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(time.strftime("%Y-%m-%dT%H:%M:%S"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--room", required=True)
    ap.add_argument("--password", default="")
    ap.add_argument("--no-launch", action="store_true",
                    help="не перезапускать игру (уже открыта)")
    ap.add_argument("--boot-wait", type=float, default=20.0)
    ap.add_argument("--marker", default=os.path.join(ROOT, "accept.flag"))
    ap.add_argument("--shot", default="")
    ap.add_argument("--settle", type=float, default=18.0,
                    help="сколько ждать после входа")
    args = ap.parse_args()

    if not args.no_launch:
        adb("shell", "am", "force-stop", "com.Hypper")
        time.sleep(3)
        adb("shell", "am", "start", "-n", PKG)
        time.sleep(args.boot_wait)

    tap(*TAP_MULTIPLAYER, wait=4.5)
    tap(*TAP_SERVER_LIST, wait=5.5)

    tap(*TAP_SEARCH, wait=0.7)
    key(123)            # MOVE_END
    key(67, 20)         # DEL x20 — очистить поле
    time.sleep(0.4)
    text(args.room)
    time.sleep(2.5)

    touch_marker(args.marker)
    tap(*TAP_FIRST_ROW, wait=3.0)

    if args.password:
        tap(*TAP_PASSWORD_FIELD, wait=0.8)
        text(args.password)
        time.sleep(0.6)
        tap(*TAP_KEYBOARD_OK, wait=1.0)
        tap(*TAP_JOIN, wait=2.0)

    print(f"join sequence done for '{args.room}'", flush=True)
    time.sleep(args.settle)

    if args.shot:
        shot(args.shot)
        print(f"screenshot: {args.shot}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())