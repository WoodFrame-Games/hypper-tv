"""Собирает автономный hypper_tv.py из модулей PhotonPy."""
import base64
import io
import zlib

BASE = r"C:\Work\Hypper\PhotonPy"
OUT = BASE + r"\hypper_tv.py"

MODULES = ["photon0509", "ptWorkFreeze", "monitor_test"]
MAIN = "monitor_video"

packed = {}
for name in MODULES:
    src = io.open(f"{BASE}\\{name}.py", encoding="utf-8").read()
    packed[name] = base64.b64encode(zlib.compress(src.encode("utf-8"), 9)).decode()

main_src = io.open(f"{BASE}\\{MAIN}.py", encoding="utf-8").read()

header = '''"""hypper_tv.py - автономный клиент: стена мониторов с видео в Hypper.

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
'''
for name in MODULES:
    header += f'    "{name}": "{packed[name]}",\n'
header += '''}

for _name, _blob in _PACKED.items():
    _mod = types.ModuleType(_name)
    _mod.__file__ = __file__
    sys.modules[_name] = _mod
    exec(compile(zlib.decompress(base64.b64decode(_blob)).decode("utf-8"),
                 _name + ".py", "exec"), _mod.__dict__)

# ---- основной сценарий (бывший monitor_video.py) ----
'''

io.open(OUT, "w", encoding="utf-8", newline="\n").write(header + main_src)
print("written", OUT)