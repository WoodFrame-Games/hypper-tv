import json
import subprocess

out = subprocess.run(
    [r"C:\msys64\ucrt64\bin\python.exe", "photon_list.py", "--json",
     "--seconds", "8", "--idle", "2", "--uid", "662c82613a01451a86960a3d03e58acd"],
    capture_output=True, text=True, encoding="utf-8").stdout
d = json.loads(out)
print("count", d["count"])
for k, v in d["rooms"].items():
    if "py" in k.lower() or "rot" in k.lower() or "test" in k.lower():
        print(repr(k), v)