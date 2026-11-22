#[derive(Clone, Debug)]
pub struct Config {
    pub room: String,
    pub cols: u32,
    pub rows: u32,
    pub cell_w: u32,
    pub cell_h: u32,
    pub size: u32,
    pub fps: f32,
    pub password: String,
    pub mode: i32,
    pub max_props: i32,
    pub max_vehicles: i32,
    pub max_players: u8,
    pub url: String,
    pub ffmpeg: String,
    pub ytdlp: String,
    pub seconds: u64,
    pub nickname: String,
    pub loop_input: bool,
}

impl Default for Config {
    fn default() -> Self {
        // Same defaults as the Android app.
        Self {
            room: "HypperTV".into(),
            cols: 7,
            rows: 5,
            cell_w: 22,
            cell_h: 12,
            size: 42,
            fps: 4.0,
            password: String::new(),
            mode: 0,
            max_props: 1000,
            max_vehicles: 40,
            max_players: 10,
            url: String::new(),
            ffmpeg: "ffmpeg".into(),
            ytdlp: "yt-dlp".into(),
            seconds: 900,
            nickname: "HypperPC".into(),
            loop_input: false,
        }
    }
}

const HELP: &str = "\
hypper-pc - video wall for Hypper (PC port of the Android app)

USAGE: hypper-pc --url <path|url> [options]

  --room NAME      room name (default HypperTV)
  --password PW    room password
  --cols N         monitors across (default 7)
  --rows N         monitors down (default 5)
  --w N            pixels per monitor X (default 22)
  --h N            pixels per monitor Y (default 12)
  --size N         text size percent (default 42)
  --fps N          frames per second (default 4)
  --seconds N      run time (default 900)
  --mode N         0 Free / 1 Private / 2 Adventure
  --max-props N    prop limit (default 1000)
  --max-vehicles N vehicle limit (default 40)
  --max-players N  player limit (default 10)
  --nick NAME      nickname in the room
  --loop           loop the video file (restart at end)
  --ffmpeg PATH    ffmpeg executable
  --ytdlp PATH     yt-dlp executable
";

fn need(it: &mut impl Iterator<Item = String>, key: &str) -> Result<String, String> {
    it.next().ok_or_else(|| format!("missing value for {key}"))
}

pub fn parse() -> Result<Option<Config>, String> {
    let mut cfg = Config::default();
    let mut it = std::env::args().skip(1);
    while let Some(a) = it.next() {
        match a.as_str() {
            "--help" | "-h" => {
                print!("{HELP}");
                return Ok(None);
            }
            "--room" => cfg.room = need(&mut it, &a)?,
            "--password" => cfg.password = need(&mut it, &a)?,
            "--url" => cfg.url = need(&mut it, &a)?,
            "--ffmpeg" => cfg.ffmpeg = need(&mut it, &a)?,
            "--ytdlp" => cfg.ytdlp = need(&mut it, &a)?,
            "--nick" => cfg.nickname = need(&mut it, &a)?,
            "--loop" => cfg.loop_input = true,
            "--cli" => {}
            "--cols" => cfg.cols = need(&mut it, &a)?.parse().map_err(|_| "bad --cols")?,
            "--rows" => cfg.rows = need(&mut it, &a)?.parse().map_err(|_| "bad --rows")?,
            "--w" => cfg.cell_w = need(&mut it, &a)?.parse().map_err(|_| "bad --w")?,
            "--h" => cfg.cell_h = need(&mut it, &a)?.parse().map_err(|_| "bad --h")?,
            "--size" => cfg.size = need(&mut it, &a)?.parse().map_err(|_| "bad --size")?,
            "--fps" => cfg.fps = need(&mut it, &a)?.parse().map_err(|_| "bad --fps")?,
            "--seconds" => cfg.seconds = need(&mut it, &a)?.parse().map_err(|_| "bad --seconds")?,
            "--mode" => cfg.mode = need(&mut it, &a)?.parse().map_err(|_| "bad --mode")?,
            "--max-props" => cfg.max_props = need(&mut it, &a)?.parse().map_err(|_| "bad --max-props")?,
            "--max-vehicles" => cfg.max_vehicles = need(&mut it, &a)?.parse().map_err(|_| "bad --max-vehicles")?,
            "--max-players" => cfg.max_players = need(&mut it, &a)?.parse().map_err(|_| "bad --max-players")?,
            other => return Err(format!("unknown option {other} (try --help)")),
        }
    }
    Ok(Some(cfg))
}
