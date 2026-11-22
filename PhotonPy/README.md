# PhotonPy — reference implementation of the video wall

These are the original Python prototypes the Android app was built from. Use
them to reproduce the same wall from a PC (for experiments, calibration and
comparison with the app).

## Files

| file | role |
| --- | --- |
| `hypper_tv.py` | main script: creates the room, spawns the wall of monitors, streams a video (YouTube / mp4 / raw RGB) as per-monitor rich text |
| `monitor_test.py` | monitor save builder (`build_save`), `enter_room`, room constants |
| `ptWorkFreeze.py` | Photon protocol 18 builders (raise event, instantiate, monitor sync, save loader) |
| `photon0509.py` | minimal Photon master / game-server client (auth, create/join room, events, ACKs) |
| `monitor_fill_test.py` | diagnostic: one monitor with a red background and green text pixels (shows how much of the panel the text really covers) |

## Requirements

- Python 3.10+ (only the standard library for the core scripts).
- For `--url` (YouTube): `yt-dlp` and `ffmpeg`. Pass their paths with
  `--ytdlp` / `--ffmpeg` (the defaults point to `C:\Work\Hypper\tools\...`).
- Without `--url` you can feed a raw RGB sequence with `--rgb` or use
  `--pattern`.

## Video wall

```bash
# YouTube link
python hypper_tv.py --room Test --password 1234 \
  --cols 7 --rows 5 --w 22 --h 12 --size 42 --fps 4 \
  --url https://youtu.be/VIDEO_ID

# local raw RGB frames (each frame: cols*w x rows*h, RGB24)
python hypper_tv.py --room Test --password 1234 --cols 3 --rows 2 \
  --w 22 --h 12 --size 42 --rgb frames.rgb

# calibration pattern (no video)
python hypper_tv.py --room Test --password 1234 --cols 7 --rows 5 --pattern
```

The script creates the room and waits for a player (`--wait-player`, default
300 s). Join the room from the game on the phone; after the player loads it
spawns the monitors 0.25 s apart and starts pushing frames.

Default geometry: step 1.73 x 1.06 m, `cx=-2`, `cz=15`, auto `cy` keeps the
bottom row at 0.6 m. Text grid 22x12 at 42% corresponds to the app's default.

## Fill test

```bash
python monitor_fill_test.py --room Fill1 --password 1234 --w 18 --h 10 --size 50
```

Spawns one monitor with `#FF0000` background and `#00FF00` pixels. Join `Fill1`
from the game and take a screenshot: black = monitor frame, red = screen area
not covered by the text, green = the pixels. Several variants at once:

```bash
python monitor_fill_test.py --room Fill2 --password 1234 \
  --grids "18x10@50,22x12@42,29x16@31"
```

## Notes

- The scripts contain the game's Photon AppId / auth constants; they are
  required to connect and are public game data extracted from the client.
- The Android app (`../hypper-android`) is the primary implementation now; these
  scripts are kept as the working reference.