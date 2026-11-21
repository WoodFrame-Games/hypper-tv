import subprocess
import sys
import time

ADB = r"C:\Users\USER\AppData\Local\Android\Sdk\platform-tools\adb.exe"
FF = r"C:\Work\Hypper\tools\ffmpeg\ffmpeg-n8.1-latest-win64-gpl-8.1\bin\ffmpeg.exe"

# область экрана монитора (полное разрешение 1520x720)
CX, CY, CW, CH = 600, 330, 80, 60


def shot() -> bytes:
    return subprocess.run([ADB, "exec-out", "screencap", "-p"],
                          capture_output=True).stdout


def avg_color(png: bytes):
    p = subprocess.run(
        [FF, "-y", "-loglevel", "error", "-i", "pipe:0",
         "-vf", f"crop={CW}:{CH}:{CX}:{CY},scale=1:1",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
        input=png, capture_output=True)
    raw = p.stdout
    if len(raw) < 3:
        return None
    return raw[0], raw[1], raw[2]


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    delay = float(sys.argv[2]) if len(sys.argv) > 2 else 0.9
    for i in range(n):
        t0 = time.time()
        png = shot()
        c = avg_color(png)
        print(f"{time.strftime('%H:%M:%S')}.{int((t0 % 1) * 1000):03d} "
              f"rgb={c} bytes={len(png)}", flush=True)
        time.sleep(delay)
    return 0


if __name__ == "__main__":
    sys.exit(main())