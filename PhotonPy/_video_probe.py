import subprocess
import sys
import time

ADB = r"C:\Users\USER\AppData\Local\Android\Sdk\platform-tools\adb.exe"
FF = r"C:\Work\Hypper\tools\ffmpeg\ffmpeg-n8.1-latest-win64-gpl-8.1\bin\ffmpeg.exe"


def shot() -> bytes:
    return subprocess.run([ADB, "exec-out", "screencap", "-p"],
                          capture_output=True).stdout


def region(png: bytes, x: int, y: int, w: int, h: int, cols: int = 3, rows: int = 2):
    p = subprocess.run(
        [FF, "-y", "-loglevel", "error", "-i", "pipe:0",
         "-vf", f"crop={w}:{h}:{x}:{y},scale={cols}:{rows}",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
        input=png, capture_output=True)
    raw = p.stdout
    return [tuple(raw[i:i + 3]) for i in range(0, len(raw), 3)]


def main() -> int:
    x, y, w, h = 590, 330, 90, 60
    if len(sys.argv) >= 5:
        x, y, w, h = (int(v) for v in sys.argv[1:5])
    n = int(sys.argv[5]) if len(sys.argv) > 5 else 6
    delay = float(sys.argv[6]) if len(sys.argv) > 6 else 0.7
    prev = None
    for i in range(n):
        png = shot()
        px = region(png, x, y, w, h)
        changed = "-" if prev is None else sum(
            1 for a, b in zip(px, prev) if abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2]) > 12)
        prev = px
        print(f"{time.strftime('%H:%M:%S')} changed={changed}/{len(px)} "
              f"avg={tuple(sum(c[k] for c in px) // len(px) for k in range(3))}", flush=True)
        time.sleep(delay)
    return 0


if __name__ == "__main__":
    sys.exit(main())