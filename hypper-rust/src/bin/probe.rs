use hypper_rust::client::{Photon, HOST, PORT};
use std::time::{Duration, Instant};

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let room = args.get(1).cloned().unwrap_or_else(|| "RustRoom".to_string());
    let hold: u64 = args.get(2).and_then(|s| s.parse().ok()).unwrap_or(40);
    let uid = "bc57d0403bb30f8d1deaba727cca5d23";

    let mut m = Photon::handshake(HOST, PORT).expect("handshake master");
    let rc = m.authenticate(uid);
    println!("master auth rc = {rc}");
    if rc != 0 {
        return;
    }
    m.join_lobby();
    let t0 = Instant::now();
    while t0.elapsed() < Duration::from_millis(1200) {
        m.pump(150);
        m.retransmit();
    }
    let (rc, gs, token) = m.create_room(&room, 10, "", false, 1, 1000, 40, "RustProbe");
    println!("create rc = {rc} gs = {gs}");
    if rc != 0 || gs.is_empty() {
        return;
    }
    drop(m);

    let (host, port) = match gs.rsplit_once(':') {
        Some((h, p)) => (h.to_string(), p.parse::<u16>().unwrap_or(PORT)),
        None => (gs.clone(), PORT),
    };
    let mut g = Photon::handshake(&host, port).expect("handshake gs");
    println!("gs auth rc = {}", g.authenticate_token(&token));
    let (rc, _, _) = g.create_room(&room, 10, "", false, 1, 1000, 40, "RustProbe");
    println!("gs create rc = {rc} actor = {:?}", g.actor);

    let vid = g.spawn_prop("Monitor", 0.0, 2.0, 15.0, 1);
    println!("spawned Monitor view={vid}");

    // шлём текст постоянно: клиент игры выбрасывает события, пока грузит карту
    // полный кадр 18x12 (~5.6 КБ) — проверяем фрагментацию
    let mut text = String::from("<size=50%>");
    for y in 0..12u32 {
        for x in 0..18u32 {
            let r = (x * 12) as u8;
            let g = (y * 20) as u8;
            text.push_str(&format!("<color=#{r:02X}{g:02X}80>\u{2588}</color>"));
        }
        text.push('\n');
    }
    text.push_str("</size>");
    println!("text len = {}", text.len());
    let end = std::time::Instant::now() + Duration::from_secs(hold);
    let mut n = 0;
    while std::time::Instant::now() < end {
        g.monitor_sync(vid, 0.0, 2.0, 15.0, (0.0, 1.0, 0.0, 0.0), &text, "#000000");
        g.keepalive(500);
        n += 1;
        if n % 20 == 0 {
            println!("sent {n} frames");
        }
    }
    println!("holding room for {hold}s (join it on the phone)");
    g.keepalive(hold * 1000);
    println!("done");
}
