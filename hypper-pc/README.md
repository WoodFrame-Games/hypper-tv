# hypper-pc

Native Windows PC port of the Android app: creates the Photon room, spawns the
wall of `Monitor` props and streams a video (local file, http(s) stream or
YouTube) as per-monitor rich text.

## GUI

Double-click `hypper-pc.exe` (or run it without arguments). Fill in the room,
password and video path, press **Старт**. The journal at the bottom shows the
same messages as the Android log. **Стоп** ends the run.

## CLI

```powershell
hypper-pc --cli --url "C:\video\movie.mp4" --room HypperTV --password 1234
```

Defaults match the Android app: 7x5 monitors, 22x12 pixels per monitor, text
size 42, 4 fps. `--help` lists every option (`--loop`, `--seconds`,
`--ffmpeg`, `--ytdlp`, ...).

## Build

```powershell
cd hypper-pc
cargo build --release
```

Video is decoded by `ffmpeg` (and `yt-dlp` for YouTube), so both must be
available in `PATH` or passed explicitly.
