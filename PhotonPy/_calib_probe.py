import re
import subprocess
import sys
import time

ADB = r"C:\Users\USER\AppData\Local\Android\Sdk\platform-tools\adb.exe"
FF = r"C:\Work\Hypper\tools\ffmpeg\ffmpeg-n8.1-latest-win64-gpl-8.1\bin\ffmpeg.exe"
W, H = 1520, 720

REGION = (560, 315, 160, 110)   # только область монитора


def shot():
    return subprocess.run([ADB, "exec-out", "screencap", "-p"],
                          capture_output=True).stdout


def raw_rgb(png: bytes) -> bytes:
    return subprocess.run([FF, "-y", "-loglevel", "error", "-i", "pipe:0",
                           "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
                          input=png, capture_output=True).stdout


def white_bbox(raw: bytes):
    x0, y0, w, h = REGION
    minx = miny = 10 ** 9
    maxx = maxy = -1
    for y in range(y0, y0 + h):
        base = y * W * 3
        for x in range(x0, x0 + w):
            i = base + x * 3
            if raw[i] > 244 and raw[i + 1] > 244 and raw[i + 2] > 244:
                if x < minx: minx = x
                if x > maxx: maxx = x
                if y < miny: miny = y
                if y > maxy: maxy = y
    if maxx < 0:
        return None
    return minx, miny, maxx, maxy


def configs_from_log(path: str):
    out = []
    try:
        for line in open(path, encoding='utf-8', errors='replace'):
            m = re.search(r'\[(\d\d:\d\d:\d\d)\] config (\d+)x(\d+)@(\d+)%', line)
            if m:
                t = sum(int(v) * k for v, k in zip(m.group(1).split(':'), (3600, 60, 1)))
                out.append((t, f"{m.group(2)}x{m.group(3)}@{m.group(4)}"))
    except FileNotFoundError:
        pass
    return out


def active(cfgs, secs: int):
    cur = None
    for t, name in cfgs:
        if t <= secs + 1:
            cur = name
    return cur


def main() -> int:
    log = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    delay = float(sys.argv[3]) if len(sys.argv) > 3 else 0.8
    best = {}
    for _ in range(n):
        t0 = time.time()
        png = shot()
        bb = white_bbox(raw_rgb(png))
        tm = time.localtime(t0)
        secs = tm.tm_hour * 3600 + tm.tm_min * 60 + tm.tm_sec
        cfg = active(configs_from_log(log), secs)
        if bb:
            x0, y0, x1, y1 = bb
            w, h = x1 - x0 + 1, y1 - y0 + 1
            asp = w / h if h else 0
            print(f"{time.strftime('%H:%M:%S', tm)} cfg={cfg} bbox={bb} "
                  f"size={w}x{h} aspect={asp:.2f}", flush=True)
            if cfg:
                best.setdefault(cfg, []).append((w, h, asp))
        else:
            print(f"{time.strftime('%H:%M:%S', tm)} cfg={cfg} no white", flush=True)
        time.sleep(delay)
    print("---- summary ----")
    for cfg, vals in best.items():
        w = max(v[0] for v in vals)
        h = max(v[1] for v in vals)
        print(f"{cfg:12} max {w}x{h} aspect {w / h:.2f}  samples={len(vals)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())