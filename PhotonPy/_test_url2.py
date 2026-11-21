import asyncio
import sys

sys.path.insert(0, r"C:\Work\Hypper\PhotonPy")
import monitor_video as mv

ARGS = (
    r"C:\Work\Hypper\tools\ytdlp\yt-dlp.exe",
    r"C:\Work\Hypper\tools\ffmpeg\ffmpeg-n8.1-latest-win64-gpl-8.1\bin\ffmpeg.exe",
)


async def check(url: str):
    print("=== ", url, flush=True)
    src = mv.UrlSource(ARGS[0], ARGS[1], url, "bv*[height<=720]", 126, 60, 2.0)
    await src.start()
    frame = await src.read()
    print("first frame:", None if frame is None else len(frame), flush=True)
    await src.stop()


async def main():
    await check("https://youtu.be/EMCtX6_-eQ8")
    await check("https://youtu.be/S2y0OTH8FOs")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))