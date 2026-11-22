# hypper-pc

Native Windows/Linux port of the Android video wall: creates the Photon room,
spawns the wall of `Monitor` props and streams a local video file (or a
YouTube/HTTP stream) as per-monitor rich text.

## Build

```powershell
cd hypper-pc
cargo build --release
```

The binary is `target/release/hypper-pc.exe`.

## Run

```powershell
hypper-pc --url "C:\video\movie.mp4" --room HypperTV --password 1234
```

Defaults match the Android app: 7x5 monitors, 22x12 pixels per monitor,
text size 42, 4 fps. `--help` lists every option.

Video is decoded by `ffmpeg` (and `yt-dlp` for YouTube links), so both must be
available in `PATH` or passed explicitly with `--ffmpeg` / `--ytdlp`.
