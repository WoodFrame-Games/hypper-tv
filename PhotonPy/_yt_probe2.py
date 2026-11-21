import subprocess

YT = r"C:\Work\Hypper\tools\ytdlp\yt-dlp.exe"
DENO = r"C:\Work\Hypper\tools\deno\deno.exe"
URL = "https://youtu.be/EMCtX6_-eQ8"

base = [YT, "--js-runtimes", f"deno:{DENO}", "--no-part", "-o", "-"]
for fmt in ("18", "bv*[vcodec^=avc1][height<=720]", "bv*[protocol^=m3u8]",
            "94/93/92", "bv*[height<=480][ext=mp4]", "b[height<=360]"):
    try:
        p = subprocess.run(base + ["-f", fmt, URL], capture_output=True, timeout=30)
        err = p.stderr.decode("utf-8", "replace")
        last = [l for l in err.strip().splitlines() if "ERROR" in l or "100%" in l]
        print(f"fmt={fmt!r} rc={p.returncode} out={len(p.stdout)} :: {last[-2:]}",
              flush=True)
    except subprocess.TimeoutExpired as e:
        out = len(e.stdout or b"")
        err = (e.stderr or b"").decode("utf-8", "replace")
        last = [l for l in err.strip().splitlines() if "ERROR" in l or "%" in l]
        print(f"fmt={fmt!r} TIMEOUT out={out} :: {last[-2:]}", flush=True)