use std::io::{Read, Write};
use std::process::{Child, Command, Stdio};

pub struct VideoSource {
    ff: Child,
    yt: Option<Child>,
    size: usize,
    pub label: String,
}

impl VideoSource {
    pub fn start(
        ffmpeg: &str,
        ytdlp: &str,
        input: &str,
        wall_w: u32,
        wall_h: u32,
        fps: f32,
        looping: bool,
    ) -> Result<Self, String> {
        let lower = input.to_lowercase();
        let youtube = lower.contains("youtu");
        if youtube {
            return Self::start_youtube(ytdlp, ffmpeg, input, wall_w, wall_h, fps);
        }
        if !(std::path::Path::new(input).is_file() || lower.starts_with("http")) {
            return Err(format!("unsupported source: {input}"));
        }
        let size = (wall_w * wall_h * 3) as usize;
        let mut ff = Command::new(ffmpeg);
        ff.args(["-loglevel", "error"]);
        if looping {
            ff.args(["-stream_loop", "-1"]);
        }
        ff.args(["-i", input, "-an"])
            .arg("-vf")
            .arg(format!("scale={wall_w}:{wall_h}:flags=neighbor,fps={fps}"))
            .args(["-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"])
            .stdout(Stdio::piped());
        let ff = ff.spawn().map_err(|e| format!("ffmpeg: {e}"))?;
        Ok(Self {
            ff,
            yt: None,
            size,
            label: input.to_string(),
        })
    }

    pub fn read_frame(&mut self) -> Option<Vec<u8>> {
        let mut buf = vec![0u8; self.size];
        match self.ff.stdout.as_mut()?.read_exact(&mut buf) {
            Ok(()) => Some(buf),
            Err(e) if e.kind() == std::io::ErrorKind::UnexpectedEof => None,
            Err(_) => None,
        }
    }

    fn start_youtube(
        ytdlp: &str,
        ffmpeg: &str,
        input: &str,
        w: u32,
        h: u32,
        fps: f32,
    ) -> Result<Self, String> {
        let mut yt = Command::new(ytdlp)
            .args(["-f", "bv*[height<=720]/b", "-o", "-", input])
            .stdout(Stdio::piped())
            .spawn()
            .map_err(|e| format!("yt-dlp: {e}"))?;
        let mut ff = Command::new(ffmpeg)
            .args(["-loglevel", "error", "-i", "pipe:0", "-an"])
            .arg("-vf")
            .arg(format!("scale={w}:{h}:flags=neighbor,fps={fps}"))
            .args(["-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .spawn()
            .map_err(|e| format!("ffmpeg: {e}"))?;
        let mut src = yt.stdout.take().ok_or("yt-dlp stdout")?;
        let mut dst = ff.stdin.take().ok_or("ffmpeg stdin")?;
        std::thread::spawn(move || {
            let _ = std::io::copy(&mut src, &mut dst);
        });
        Ok(Self {
            ff,
            yt: Some(yt),
            size: (w * h * 3) as usize,
            label: input.to_string(),
        })
    }
}
