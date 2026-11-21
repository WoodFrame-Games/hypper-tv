import re
import subprocess
import sys
import time

ADB = r"C:\Users\USER\AppData\Local\Android\Sdk\platform-tools\adb.exe"
LOG = sys.argv[1] if len(sys.argv) > 1 else r"C:\Work\Hypper\phone\cal2.log"
OUT = r"C:\Work\Hypper\phone"


def last_cfg():
    cfg = None
    for line in open(LOG, encoding='utf-8', errors='replace'):
        m = re.search(r'config (\d+x\d+@\d+)%', line)
        if m:
            cfg = m.group(1)
    return cfg


def shot(name):
    png = subprocess.run([ADB, "exec-out", "screencap", "-p"],
                         capture_output=True).stdout
    p = f"{OUT}\\{name}.png"
    open(p, "wb").write(png)
    print("saved", p, "cfg=", last_cfg(), flush=True)


wanted = sys.argv[2:] or ["20x12@50", "16x10@50"]
seen = set()
t_end = time.time() + 90
while time.time() < t_end and len(seen) < len(wanted):
    cfg = last_cfg()
    if cfg in wanted and cfg not in seen:
        time.sleep(2.0)
        shot(cfg.replace("@", "_").replace("%", ""))
        seen.add(cfg)
    time.sleep(0.3)
print("done", seen)