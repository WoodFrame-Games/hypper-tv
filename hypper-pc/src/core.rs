use hypper_rust::client::{Photon, HOST, PORT};
use std::time::{Duration, Instant};

use crate::args::Config;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::OnceLock;

static LOG: OnceLock<Box<dyn Fn(String) + Send + Sync>> = OnceLock::new();
pub static STOP: AtomicBool = AtomicBool::new(false);

pub fn set_logger(f: impl Fn(String) + Send + Sync + 'static) {
    let _ = LOG.set(Box::new(f));
}

pub fn emit(s: String) {
    match LOG.get() {
        Some(f) => f(s),
        None => println!("{s}"),
    }
}

macro_rules! log {
    ($($a:tt)*) => { crate::core::emit(format!($($a)*)) };
}
use crate::video::VideoSource;

const UID: &str = "bc57d0403bb30f8d1deaba727cca5d23";
const MON_W: f32 = 1.73;
const MON_H: f32 = 1.06;
const Z: f32 = 15.0;

fn wall_pos(i: u32, cols: u32, rows: u32) -> (f32, f32) {
    let col = (i % cols) as f32;
    let row = (i / cols) as f32;
    let width = cols as f32 * MON_W;
    let x = -2.0 - width / 2.0 + MON_W / 2.0 + col * MON_W;
    let cy = 2.0 + (rows as f32 - 1.0) * MON_H / 2.0;
    let y = cy + ((rows as f32 - 1.0) / 2.0 - row) * MON_H;
    (x, y)
}

fn cell_text(frame: &[u8], ww: usize, wh: usize, x0: usize, y0: usize,
             w: u32, h: u32, size: u32) -> String {
    let mut s = String::with_capacity(6200);
    s.push_str(&format!("<size={size}%><b>"));
    for y in 0..h as usize {
        let sy = (y0 + (h as usize - 1 - y)).min(wh - 1);
        let mut x = 0usize;
        while x < w as usize {
            let gx = (x0 + (w as usize - 1 - x)).min(ww - 1);
            let i = (sy * ww + gx) * 3;
            let (r, g, b) = if i + 2 < frame.len() {
                (frame[i] >> 4, frame[i + 1] >> 4, frame[i + 2] >> 4)
            } else {
                (0, 0, 0)
            };
            let mut x2 = x + 1;
            while x2 < w as usize {
                let gx2 = (x0 + (w as usize - 1 - x2)).min(ww - 1);
                let i2 = (sy * ww + gx2) * 3;
                let same = i2 + 2 < frame.len()
                    && (frame[i2] >> 4) == r
                    && (frame[i2 + 1] >> 4) == g
                    && (frame[i2 + 2] >> 4) == b;
                if !same {
                    break;
                }
                x2 += 1;
            }
            s.push_str(&format!("<color=#{r:X}{g:X}{b:X}>"));
            for _ in x..x2 {
                s.push('\u{2588}');
            }
            s.push_str("</color>");
            x = x2;
        }
        if y + 1 < h as usize {
            s.push('\n');
        }
    }
    s.push_str("</b></size>");
    s
}

fn connect(host: &str, port: u16) -> Result<Photon, String> {
    for attempt in 1..=6 {
        if STOP.load(Ordering::Relaxed) {
            return Err("stopped".into());
        }
        match Photon::handshake(host, port) {
            Ok(p) => return Ok(p),
            Err(e) => {
                log!("handshake attempt {attempt}: {e}");
                std::thread::sleep(Duration::from_millis(1500));
            }
        }
    }
    Err(format!("cannot connect to {host}:{port}"))
}

pub fn run(cfg: Config) -> Result<(), String> {
    STOP.store(false, Ordering::Relaxed);
    let n = cfg.cols * cfg.rows;
    if n == 0 || n > 1000 {
        return Err(format!("bad wall size: {n} props"));
    }
    if cfg.url.is_empty() {
        return Err("no --url given".into());
    }
    let wall_w = cfg.cols * cfg.cell_w;
    let wall_h = cfg.rows * cfg.cell_h;
    log!("room: {} ({}x{})", cfg.room, cfg.cols, cfg.rows);
    log!("wall: {wall_w}x{wall_h} px, {n} objects");
    let mut m = connect(HOST, PORT)?;
    let rc = m.authenticate(UID);
    log!("auth rc={rc}");
    if rc != 0 {
        return Err(format!("auth failed rc={rc}"));
    }
    m.join_lobby();
    m.pump(1200);
    m.retransmit();
    let (rc, gs, token) = m.create_room(
        &cfg.room, cfg.max_players, &cfg.password, true, cfg.mode,
        cfg.max_props, cfg.max_vehicles, &cfg.nickname,
    );
    log!("create rc={rc} gs={gs}");
    if rc != 0 || gs.is_empty() {
        return Err(format!("create failed rc={rc}"));
    }
    drop(m);
    let (gh, gp) = match gs.rsplit_once(':') {
        Some((h, p)) => (h.to_string(), p.parse().unwrap_or(PORT)),
        None => (gs.clone(), PORT),
    };
    let mut g = connect(&gh, gp)?;
    let rc = g.authenticate_token(&token);
    log!("gs auth rc={rc}");
    if rc != 0 {
        return Err(format!("gs auth failed rc={rc}"));
    }
    let (rc, _, _) = g.create_room(
        &cfg.room, cfg.max_players, &cfg.password, true, cfg.mode,
        cfg.max_props, cfg.max_vehicles, &cfg.nickname,
    );
    log!("gs create rc={rc}");
    if rc != 0 {
        return Err(format!("gs create failed rc={rc}"));
    }
    let _ = g.wait_in_room(8000);
    log!("in room, actor={:?}", g.actor);
    let mut src = VideoSource::start(
        &cfg.ffmpeg, &cfg.ytdlp, &cfg.url, wall_w, wall_h, cfg.fps,
        cfg.start_sec, cfg.loop_input,
    )?;
    log!("source: {}", src.label);
    let first = src.read_frame().ok_or("no video frames")?;
    let mut vids = Vec::with_capacity(n as usize);
    for i in 0..n {
        if STOP.load(Ordering::Relaxed) {
            return Ok(());
        }
        let (x, y) = wall_pos(i, cfg.cols, cfg.rows);
        let vid = g.spawn_prop("Monitor", x, y, Z, 801 + i);
        log!("monitor #{i} view={vid}");
        vids.push(vid);
        g.keepalive(300);
    }
    let period = Duration::from_secs_f32(1.0 / cfg.fps.max(0.5));
    let end = cfg.seconds.map(|s| Instant::now() + Duration::from_secs(s));
    let mut frame = first;
    let mut last = Instant::now();
    let mut sent = 0u64;
    while !STOP.load(Ordering::Relaxed) && end.map_or(true, |e| Instant::now() < e) {
        for i in 0..n {
            let col = i % cfg.cols;
            let row = i / cfg.cols;
            let (x, y) = wall_pos(i, cfg.cols, cfg.rows);
            let text = cell_text(
                &frame, wall_w as usize, wall_h as usize,
                (col * cfg.cell_w) as usize, (row * cfg.cell_h) as usize,
                cfg.cell_w, cfg.cell_h, cfg.size,
            );
            g.monitor_sync(vids[i as usize], x, y, Z, (0.0, 1.0, 0.0, 0.0),
                           &text, "#000000");
            if i % 16 == 15 {
                g.retransmit();
            }
        }
        sent += 1;
        let left = period.saturating_sub(last.elapsed());
        std::thread::sleep(left);
        last = Instant::now();
        g.pump(5);
        g.retransmit();
        match src.read_frame() {
            Some(f) => frame = f,
            None => break,
        }
    }
    log!("done, {sent} frames");
    Ok(())
}
