import asyncio
import sys

sys.path.insert(0, r"C:\Work\Hypper\PhotonPy")
import monitor_video as mv


async def main() -> int:
    src = mv.UrlSource(
        r"C:\Work\Hypper\tools\ytdlp\yt-dlp.exe",
        r"C:\Work\Hypper\tools\ffmpeg\ffmpeg-n8.1-latest-win64-gpl-8.1\bin\ffmpeg.exe",
        "https://youtu.be/S2y0OTH8FOs",
        "bv*[height<=720]",
        126, 60, 2.0)
    await src.start()
    for i in range(6):
        frame = await src.read()
        if frame is None:
            print("EOF/err at", i)
            break
        avg = sum(frame) // len(frame)
        print(f"frame {i}: {len(frame)} bytes, avg={avg}", flush=True)
    await src.stop()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))