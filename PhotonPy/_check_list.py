import json
import subprocess

out = subprocess.run(
    [r"C:\msys64\ucrt64\bin\python.exe", "photon_list.py", "--json",
     "--seconds", "7", "--idle", "2", "--uid", "662c82613a01451a86960a3d03e58acd"],
    capture_output=True, text=True, encoding="utf-8").stdout
d = json.loads(out)
print("count", d["count"])
for k, v in list(d["rooms"].items())[:8]:
    print(f"{k[:28]:30} {v.get('players')}/{v.get('max')}  {v.get('map')}  mode={v.get('gamemode')}")
print("PyTest:", d["rooms"].get("PyTest"))