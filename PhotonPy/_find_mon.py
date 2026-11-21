import subprocess
import sys

ADB = r"C:\Users\USER\AppData\Local\Android\Sdk\platform-tools\adb.exe"
FF = r"C:\Work\Hypper\tools\ffmpeg\ffmpeg-n8.1-latest-win64-gpl-8.1\bin\ffmpeg.exe"

W, H = 1520, 720

png = subprocess.run([ADB, "exec-out", "screencap", "-p"], capture_output=True).stdout
p = subprocess.run([FF, "-y", "-loglevel", "error", "-i", "pipe:0",
                    "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
                   input=png, capture_output=True)
raw = p.stdout
print("raw bytes", len(raw), "expected", W * H * 3)

x0, x1, y0, y1 = 350, 1000, 220, 480
minx, maxx, miny, maxy = 10 ** 9, -1, 10 ** 9, -1
cnt = 0
for y in range(y0, y1):
    base = y * W * 3
    for x in range(x0, x1):
        i = base + x * 3
        r, g, b = raw[i], raw[i + 1], raw[i + 2]
        if r < 45 and g < 45 and b < 45:
            cnt += 1
            if x < minx: minx = x
            if x > maxx: maxx = x
            if y < miny: miny = y
            if y > maxy: maxy = y
print("dark pixels:", cnt, "bbox:", minx, miny, maxx, maxy)