//! JNI-обёртка над hypper-rust для Android-приложения.
//!
//! MainActivity вызывает nativeStart("<key=value;...>") и nativeStop().

use hypper_rust::client::{Photon, HOST, PORT};
use jni::objects::{JClass, JString};
use jni::JNIEnv;
use jni::JavaVM;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, OnceLock};
use std::time::{Duration, Instant};

static VM: OnceLock<Arc<JavaVM>> = OnceLock::new();
static RUNNING: AtomicBool = AtomicBool::new(false);

#[derive(Clone, Debug)]
struct Cfg {
    room: String,
    cols: u32,
    rows: u32,
    cell_w: u32,
    cell_h: u32,
    text_size: u32,
    fps: f32,
    mode: i32,
    max_players: u8,
    password: String,
    max_props: i32,
    max_vehicles: i32,
    wait_ready_secs: u32,
    pattern: bool,
    cy: f32,
}

fn parse_cfg(raw: &str) -> Cfg {
    let mut c = Cfg {
        room: "PhoneTV".into(),
        cols: 7,
        rows: 5,
        cell_w: 18,
        cell_h: 10,
        text_size: 50,
        fps: 2.0,
        mode: 0,
        max_players: 10,
        password: String::new(),
        max_props: 1000,
        max_vehicles: 40,
        wait_ready_secs: 20,
        pattern: false,
        cy: 0.0,
    };
    for part in raw.split(';') {
        let mut it = part.splitn(2, '=');
        let k = it.next().unwrap_or("").trim();
        let v = it.next().unwrap_or("").trim();
        match k {
            "room" => c.room = v.to_string(),
            "cols" => c.cols = v.parse().unwrap_or(c.cols),
            "rows" => c.rows = v.parse().unwrap_or(c.rows),
            "w" => c.cell_w = v.parse().unwrap_or(c.cell_w),
            "h" => c.cell_h = v.parse().unwrap_or(c.cell_h),
            "size" => c.text_size = v.parse().unwrap_or(c.text_size),
            "fps" => c.fps = v.parse().unwrap_or(c.fps),
            "mode" => c.mode = v.parse().unwrap_or(c.mode),
            "max" => c.max_players = v.parse().unwrap_or(c.max_players),
            "password" => c.password = v.to_string(),
            "props" => c.max_props = v.parse().unwrap_or(c.max_props),
            "vehicles" => c.max_vehicles = v.parse().unwrap_or(c.max_vehicles),
            "wait" => c.wait_ready_secs = v.parse().unwrap_or(c.wait_ready_secs),
            "pattern" => c.pattern = v == "1" || v.eq_ignore_ascii_case("true"),
            "cy" => c.cy = v.parse().unwrap_or(0.0),
            _ => {}
        }
    }
    c.cols = c.cols.clamp(1, 40);
    c.rows = c.rows.clamp(1, 25);
    c.cell_w = c.cell_w.clamp(1, 18);
    c.cell_h = c.cell_h.clamp(1, 12);
    c.text_size = c.text_size.clamp(10, 200);
    c.fps = if c.fps.is_finite() {
        c.fps.clamp(0.2, 30.0)
    } else {
        2.0
    };
    c.max_players = c.max_players.clamp(1, 100);
    c.max_props = c.max_props.clamp(1, 1000);
    c.max_vehicles = c.max_vehicles.clamp(0, 40);
    c
}

/// Match Python's load gate: don't spawn until another game client has joined
/// and emitted its own Instantiate (event 202), or the user-configured timeout.
fn wait_for_game_client(g: &mut Photon, vm: &JavaVM, timeout_secs: u32) -> bool {
    if timeout_secs == 0 {
        log(vm, "ожидание игрока отключено; строю стену сразу");
        return false;
    }
    let owner = g.actor.unwrap_or(1);
    let deadline = Instant::now() + Duration::from_secs(timeout_secs.min(300) as u64);
    let mut joining_actor = None;
    log(
        vm,
        &format!(
            "комната открыта; жду входа игрока и окончания загрузки (до {} с)",
            timeout_secs.min(300)
        ),
    );
    while RUNNING.load(Ordering::Relaxed) && Instant::now() < deadline {
        g.keepalive(200);
        for (mtype, data) in g.drain_backlog() {
            if mtype != 4 || data.is_empty() {
                continue;
            }
            match data[0] {
                255 => {
                    if let Some(actor) = hypper_rust::client::event_actor(&data) {
                        if actor != owner {
                            joining_actor = Some(actor);
                            log(vm, &format!("игрок {actor} вошёл; жду завершения загрузки"));
                        }
                    }
                }
                202 => {
                    if let (Some(actor), Some(view)) = (
                        joining_actor,
                        hypper_rust::client::event_int(&data, 7),
                    ) {
                        if view / 1000 == actor {
                            log(vm, &format!("игрок {actor} загрузил мир; строю стену"));
                            return true;
                        }
                    }
                }
                _ => {}
            }
        }
    }
    if RUNNING.load(Ordering::Relaxed) {
        log(vm, "игрок не дождался; строю стену сейчас (поздние клиенты получат resync)");
    }
    false
}

/// Keep join/ready messages visible after wall construction; each following
/// frame is a complete state resync, matching the Python reference behaviour.
fn log_room_events(g: &mut Photon, vm: &JavaVM, owner: u32) -> bool {
    let mut joined = false;
    for (mtype, data) in g.drain_backlog() {
        if mtype != 4 || data.is_empty() {
            continue;
        }
        if data[0] == 255 {
            if let Some(actor) = hypper_rust::client::event_actor(&data) {
                if actor != owner {
                    log(vm, &format!("игрок {actor} подключился; состояние мониторов обновляется"));
                    joined = true;
                }
            }
        } else if data[0] == 202 {
            if let Some(view) = hypper_rust::client::event_int(&data, 7) {
                let actor = view / 1000;
                if actor != owner {
                    log(vm, &format!("игрок {actor} закончил загрузку"));
                }
            }
        }
    }
    joined
}

static LOGS: Mutex<Vec<String>> = Mutex::new(Vec::new());

/// Кадр, присланный из Java (MediaMetadataRetriever): RGB24, wall_w x wall_h.
static FRAME: Mutex<Option<(usize, usize, Vec<u8>)>> = Mutex::new(None);

fn log(_vm: &JavaVM, msg: &str) {
    // В потоке, привязанном к JVM, classloader приложения не виден, поэтому
    // не зовём Java напрямую — копим строки, Java забирает их сама.
    if let Ok(mut v) = LOGS.lock() {
        v.push(msg.to_string());
        if v.len() > 500 {
            let cut = v.len() - 500;
            v.drain(0..cut);
        }
    }
}

/// Текст панели из кадра (RGB24, размер wall_w x wall_h).
fn cell_text_from_frame(
    frame: &[u8],
    wall_w: usize,
    wall_h: usize,
    x0: usize,
    y0: usize,
    w: u32,
    h: u32,
    size: u32,
) -> String {
    let mut s = String::with_capacity(6200);
    s.push_str(&format!("<size={size}%>"));
    for y in 0..h as usize {
        s.push_str("<b>");
        // Monitor renders the text upside down (scale.y = -1) as well as
        // mirrored, so pre-flip the row order to keep the picture upright.
        let sy = (y0 + (h as usize - 1 - y)).min(wall_h - 1);
        for x in 0..w as usize {
            // Monitor is rotated 180° about Y, so the game mirrors its text
            // horizontally. Pre-mirror the crop to cancel that out.
            let gx = (x0 + (w as usize - 1 - x)).min(wall_w - 1);
            let gy = sy;
            let i = (gy * wall_w + gx) * 3;
            if i + 2 < frame.len() {
                s.push_str(&format!(
                    "<color=#{:X}{:X}{:X}>\u{2588}</color>",
                    frame[i] >> 4, frame[i + 1] >> 4, frame[i + 2] >> 4
                ));
            }
        }
        s.push_str("</b>");
        if y + 1 < h as usize {
            s.push('\n');
        }
    }
    s.push_str("</size>");
    s
}

/// Текст одной панели: кадр cols*rows, вырезаем cell x cell.
fn cell_text(
    wall_w: u32,
    wall_h: u32,
    x0: u32,
    y0: u32,
    w: u32,
    h: u32,
    size: u32,
) -> String {
    // Diagnostic gradient across the WHOLE wall: R grows left→right,
    // G grows top→bottom. Any tile flip/shift breaks the smooth ramp.
    let ww = wall_w.max(2) - 1;
    let hh = wall_h.max(2) - 1;
    let mut s = String::with_capacity(2400);
    s.push_str(&format!("<size={size}%>"));
    for y in 0..h {
        s.push_str("<b>");
        for x in 0..w {
            let gx = (x0 + (w - 1 - x)).min(ww);
            let gy = (y0 + (h - 1 - y)).min(hh);
            let r = (gx * 255 / ww) as u8;
            let g = (gy * 255 / hh) as u8;
            s.push_str(&format!("<color=#{r:02X}{g:02X}40>\u{2588}</color>"));
        }
        s.push_str("</b>");
        if y + 1 < h {
            s.push('\n');
        }
    }
    s.push_str("</size>");
    s
}

/// Калибровочная плитка: сплошной цвет по колонке, яркость по ряду,
/// белый квадрат в верхнем-левом углу (для проверки переворотов).
fn pattern_text(idx: u32, cols: u32, w: u32, h: u32, size: u32) -> String {
    const HUE: [(u8, u8, u8); 7] = [
        (255, 0, 0),
        (255, 128, 0),
        (255, 255, 0),
        (0, 255, 0),
        (0, 255, 255),
        (0, 0, 255),
        (255, 0, 255),
    ];
    let col = (idx % cols) as usize;
    let row = idx / cols;
    let (mut r, mut g, mut b) = HUE[col % HUE.len()];
    let dim = |c: u8, k: u32| -> u8 { ((c as u32) * k / 255).min(255) as u8 };
    let k = 255u32.saturating_sub(row * 45).max(40);
    r = dim(r, k);
    g = dim(g, k);
    b = dim(b, k);
    let mut s = String::with_capacity(2400);
    s.push_str(&format!("<size={size}%>"));
    for y in 0..h as usize {
        s.push_str("<b>");
        for x in 0..w as usize {
            // Pre-mirror like cell_text_from_frame (monitor mirrors by 180° Y).
            let mx = w as usize - 1 - x;
            // белый маркер 4x4 в верхнем-левом углу (с учётом переворота Y)
            let marker_row = y + 4 >= h as usize;
            let color = if mx < 4 && marker_row {
                "#FFF".to_string()
            } else {
                format!("#{r:02X}{g:02X}{b:02X}")
            };
            s.push_str(&format!("<color={color}>\u{2588}</color>"));
        }
        s.push_str("</b>");
        if y + 1 < h as usize {
            s.push('\n');
        }
    }
    s.push_str("</size>");
    s
}

fn worker(vm: Arc<JavaVM>, cfg: Cfg) {
    log(&vm, &format!("комната: {} ({}x{})", cfg.room, cfg.cols, cfg.rows));

    let mut m = match Photon::handshake(HOST, PORT) {
        Ok(p) => p,
        Err(e) => {
            log(&vm, &format!("нет связи с Photon: {e}"));
            return;
        }
    };
    let rc = m.authenticate("bc57d0403bb30f8d1deaba727cca5d23");
    log(&vm, &format!("auth rc={rc}"));
    if rc != 0 {
        return;
    }
    m.join_lobby();
    let t = Instant::now();
    while t.elapsed() < Duration::from_millis(1200) && RUNNING.load(Ordering::Relaxed) {
        m.pump(150);
        m.retransmit();
    }
    let (rc, gs, token) = m.create_room(
        &cfg.room,
        cfg.max_players,
        &cfg.password,
        false,
        cfg.mode,
        cfg.max_props,
        cfg.max_vehicles,
        "Hypper TV",
    );
    log(&vm, &format!("create rc={rc} gs={gs}"));
    if rc != 0 {
        return;
    }
    // Python reference closes the Master peer before opening the GameServer
    // peer. Keeping both sockets alive can leave the Master reservation stale.
    drop(m);
    let (host, port) = match gs.rsplit_once(':') {
        Some((h, p)) => (h.to_string(), p.parse::<u16>().unwrap_or(PORT)),
        None => (gs.clone(), PORT),
    };
    let mut g = match Photon::handshake(&host, port) {
        Ok(p) => p,
        Err(e) => {
            log(&vm, &format!("нет связи с GS: {e}"));
            return;
        }
    };
    let rc = g.authenticate_token(&token);
    log(&vm, &format!("gs auth rc={rc}"));
    if rc != 0 {
        return;
    }
    let (rc, _, _) = g.create_room(
        &cfg.room,
        cfg.max_players,
        &cfg.password,
        false,
        cfg.mode,
        cfg.max_props,
        cfg.max_vehicles,
        "Hypper TV",
    );
    if rc != 0 {
        if rc == 32766 {
            log(
                &vm,
                &format!(
                    "комната «{}» уже существует (GameIdAlreadyExists); выберите другое имя",
                    cfg.room
                ),
            );
        } else {
            log(
                &vm,
                &format!("GameServer не создал/не открыл комнату: rc={rc}"),
            );
        }
        return;
    }
    log(&vm, &format!("в комнате, rc={rc} actor={:?}", g.actor));
    if !RUNNING.load(Ordering::Relaxed) {
        return;
    }
    wait_for_game_client(&mut g, &vm, cfg.wait_ready_secs);
    if !RUNNING.load(Ordering::Relaxed) {
        return;
    }

    // 34x8 at 30% is what actually fills a Monitor on the phone: the game
    // auto-scales the text block, and at 50% only ~5 of 12 rows were visible.
    let (src_w, src_h) = (cfg.cell_w, cfg.cell_h);
    let (cw, ch) = (cfg.cell_w, cfg.cell_h);
    let (mon_w, mon_h) = (1.73f32, 1.06f32);
    let requested = cfg.cols.saturating_mul(cfg.rows);
    let total = requested.min(cfg.max_props as u32).min(1000);
    if total < requested {
        log(&vm, &format!("стена ограничена лимитом: {total}/{} панелей", requested));
    }
    let width = cfg.cols as f32 * mon_w;
    let cx0 = -2.0;
    // Python's --cy: keep the bottom row clear of the ground.
    // At y=0.6 the game silently refuses the Monitor, so start at 1.2 m.
    let cy = if cfg.cy > 0.0 {
        cfg.cy
    } else {
        2.0 + (cfg.rows as f32 - 1.0) * mon_h / 2.0
    };
    // Python allocates sub-ids from 800: lower ids belong to the game's own
    // scene objects, so reusing them drops/overwrites monitors.
    let sub_base: u32 = 800;
    let mut vids: Vec<u32> = Vec::with_capacity(total as usize);
    for i in 0..total {
        let col = (i % cfg.cols) as f32;
        let row = (i / cfg.cols) as f32;
        let x = cx0 - width / 2.0 + mon_w / 2.0 + col * mon_w;
        // Python wall_pos(): bottom row sits at y=0.6; wall grows upwards.
        let y = cy + ((cfg.rows as f32 - 1.0) / 2.0 - row) * mon_h;
        let vid = g.spawn_prop("Monitor", x, y, 15.0, sub_base + i + 1);
        vids.push(vid);
        if i % 10 == 0 || i + 1 == total {
            log(&vm, &format!("панель {}/{} view={vid}", i + 1, total));
        }
        // Python uses a 250 ms gap: a denser burst makes the client drop the
        // tail of the Instantiate stream (last wall row never appeared).
        g.keepalive(300);
        if !RUNNING.load(Ordering::Relaxed) {
            return;
        }
    }
    log(&vm, "стена построена, гоняю кадры");
    let owner = g.actor.unwrap_or(1);
    let mut full_resync = log_room_events(&mut g, &vm, owner);

    let period = Duration::from_secs_f32(1.0 / cfg.fps.max(0.2));
    let mut frame: u32 = 0;
    let mut last_text = vec![String::new(); total as usize];
    let mut last_refresh = Instant::now();
    while RUNNING.load(Ordering::Relaxed) {
        if last_refresh.elapsed() >= Duration::from_secs(10) {
            full_resync = true;
            last_refresh = Instant::now();
            log(&vm, "периодический resync стены");
        }
        let sync_all = full_resync;
        full_resync = false;
        // Freeze one RGB frame for the entire wall cycle. Java may push the
        // next frame while this thread serializes panels; reading FRAME inside
        // the tile loop would mix pixels from two source frames.
        let frame_snapshot = FRAME.lock().ok().and_then(|guard| {
            guard
                .as_ref()
                .map(|(fw, fh, bytes)| (*fw, *fh, bytes.clone()))
        });
        let t0 = Instant::now();
        for i in 0..total {
            let col = i % cfg.cols;
            let row = i / cfg.cols;
            let (text, _bg) = if cfg.pattern {
                (
                    pattern_text(i, cfg.cols, cw, ch, cfg.text_size),
                    String::new(),
                )
            } else if let Some((fw, fh, data)) = frame_snapshot.as_ref() {
                if *fw == (cfg.cols * src_w) as usize && *fh == (cfg.rows * src_h) as usize {
                    (
                        cell_text_from_frame(
                            data,
                            *fw,
                            *fh,
                            (col * src_w) as usize,
                            (row * src_h) as usize,
                            cw,
                            ch,
                            cfg.text_size,
                        ),
                        String::new(),
                    )
                } else {
                    (
                        cell_text(
                            cfg.cols * cw,
                            cfg.rows * ch,
                            col * cw,
                            row * ch,
                            cw,
                            ch,
                            cfg.text_size,
                        ),
                        String::new(),
                    )
                }
            } else {
                (
                    cell_text(
                        cfg.cols * cw,
                        cfg.rows * ch,
                        col * cw,
                        row * ch,
                        cw,
                        ch,
                        cfg.text_size,
                    ),
                    String::new(),
                )
            };
            let colf = col as f32;
            let rowf = row as f32;
            let x = cx0 - width / 2.0 + mon_w / 2.0 + colf * mon_w;
            let y = cy + ((cfg.rows as f32 - 1.0) / 2.0 - rowf) * mon_h;
            let vid = vids[i as usize];
            if sync_all || last_text[i as usize] != text {
                // Как в старом скрипте: фон панели чёрный (Monitor.Color).
                g.monitor_sync(vid, x, y, 15.0, (0.0, 1.0, 0.0, 0.0), &text, "#000000");
                last_text[i as usize] = text;
            }
            if (i + 1) % 16 == 0 {
                g.keepalive(20);
                full_resync |= log_room_events(&mut g, &vm, owner);
            }
        }
        frame = frame.wrapping_add(1);
        g.keepalive(20);
        full_resync |= log_room_events(&mut g, &vm, owner);
        if frame % 5 == 0 {
            log(&vm, &format!("кадр {frame}"));
        }
        let spent = t0.elapsed();
        if spent < period {
            g.keepalive((period - spent).as_millis() as u64);
        }
    }
    log(&vm, "остановлено");
}

#[no_mangle]
pub extern "system" fn Java_com_hypper_tv_MainActivity_nativeStart(
    mut env: JNIEnv,
    _class: JClass,
    cfg: JString,
) -> jni::sys::jboolean {
    let raw: String = match env.get_string(&cfg) {
        Ok(s) => s.into(),
        Err(_) => return 0,
    };
    let vm = match env.get_java_vm() {
        Ok(v) => v,
        Err(_) => return 0,
    };
    let vm = Arc::new(vm);
    let _ = VM.set(vm.clone());
    if let Ok(mut frame) = FRAME.lock() {
        *frame = None;
    }
    RUNNING.store(true, Ordering::Relaxed);
    let cfg = parse_cfg(&raw);
    // панику в рабочем потоке ловим, иначе процесс падает целиком
    std::panic::set_hook(Box::new(|info| {
        if let Ok(mut v) = LOGS.lock() {
            v.push(format!("ПАНИКА: {info}"));
        }
    }));
    std::thread::spawn(move || {
        let vm2 = vm.clone();
        let res = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| worker(vm2, cfg)));
        if res.is_err() {
            log(&vm, "поток остановлен из-за паники");
        }
        RUNNING.store(false, Ordering::Relaxed);
    });
    1
}

#[no_mangle]
pub extern "system" fn Java_com_hypper_tv_MainActivity_nativeIsRunning(
    _env: JNIEnv,
    _class: JClass,
) -> jni::sys::jboolean {
    if RUNNING.load(Ordering::Relaxed) {
        1
    } else {
        0
    }
}

#[no_mangle]
pub extern "system" fn Java_com_hypper_tv_MainActivity_nativePushFrame(
    env: JNIEnv,
    _class: JClass,
    data: jni::objects::JByteArray,
    w: jni::sys::jint,
    h: jni::sys::jint,
) {
    if w <= 0 || h <= 0 {
        return;
    }
    if !RUNNING.load(Ordering::Relaxed) {
        return;
    }
    if let Ok(bytes) = env.convert_byte_array(&data) {
        if let Ok(mut g) = FRAME.lock() {
            *g = Some((w as usize, h as usize, bytes));
        }
    }
}

#[no_mangle]
pub extern "system" fn Java_com_hypper_tv_MainActivity_nativeLogDrain(
    env: JNIEnv,
    _class: JClass,
) -> jni::sys::jstring {
    let text = {
        let mut v = match LOGS.lock() {
            Ok(v) => v,
            Err(_) => return std::ptr::null_mut(),
        };
        let out = v.join("\n");
        v.clear();
        out
    };
    match env.new_string(text) {
        Ok(s) => s.into_raw(),
        Err(_) => std::ptr::null_mut(),
    }
}

#[no_mangle]
pub extern "system" fn Java_com_hypper_tv_MainActivity_nativeStop(
    _env: JNIEnv,
    _class: JClass,
) {
    RUNNING.store(false, Ordering::Relaxed);
}
