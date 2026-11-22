//! Фотон-клиент 0.5.0.9: UDP (EnetPeer), фрагментация, ACK, ретрансмит.

use crate::proto::{build_op, room_props, Val};
use hmac::{Hmac, Mac};
use rand::Rng;
use sha2::Sha256;
use std::collections::HashMap;
use std::io;
use std::net::UdpSocket;
use std::time::{Duration, Instant};

pub const HOST: &str = "82.158.120.189";
pub const PORT: u16 = 5055;
pub const APP_ID: &str = "b6c0c507-d9ea-4e0b-ae1a-930bd1240323";
pub const APP_VER: &str = "0.5.0.9";
pub const CLIENT_VER: &str = "4.1.8.23";
pub const SECRET: &[u8] = &[
    0x5f, 0xbe, 0x71, 0x0f, 0xbd, 0x13, 0xfc, 0xf3, 0x32, 0x38, 0x8f, 0xe3, 0xda, 0xc4, 0x52, 0xb5,
    0x18, 0xb9, 0xb1, 0x60, 0xdd, 0xf6, 0x89, 0xc9, 0x1d, 0x52, 0xeb, 0x1a, 0x69, 0xa0, 0x60, 0x4e,
];
pub const CONNECT_PAYLOAD: &[u8] = &[
    0x00, 0x00, 0x04, 0xb0, 0x00, 0x00, 0x80, 0x00, 0x00, 0x00, 0x00, 0x02, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x13, 0x88, 0x00, 0x00, 0x00, 0x02, 0x00, 0x00, 0x00, 0x02,
];

const T_ACK: u8 = 1;
const T_CONNECT: u8 = 2;
const T_VERIFY: u8 = 3;
const T_PING: u8 = 5;
const T_RELIABLE: u8 = 6;
const T_FRAGMENT: u8 = 8;

const MTU: usize = 1200;
const FRAG_CHUNK: usize = MTU - 12 - 12 - 20;

pub fn sign_for(uid: &str) -> String {
    let mut mac = <Hmac<Sha256> as Mac>::new_from_slice(SECRET).expect("hmac");
    mac.update(uid.as_bytes());
    hex::encode_upper(mac.finalize().into_bytes())
}

#[derive(Clone)]
struct Pending {
    cmd: Vec<u8>,
    at: Instant,
    tries: u8,
}

pub struct Photon {
    sock: UdpSocket,
    peer_id: u16,
    challenge: u32,
    t0: Instant,
    seq: HashMap<u8, u32>,
    pending: HashMap<u32, Pending>,
    backlog: Vec<(u8, Vec<u8>)>,
    last_ping: Instant,
    pub debug: bool,
    pub actor: Option<u32>,
    disconnect: Option<String>,
}

impl Photon {
    fn ms(&self) -> u32 {
        self.t0.elapsed().as_millis() as u32
    }

    fn command(&self, ctype: u8, ch: u8, flags: u8, seq: u32, payload: &[u8]) -> Vec<u8> {
        let mut v = Vec::with_capacity(12 + payload.len());
        v.push(ctype);
        v.push(ch);
        v.push(flags);
        v.push(4);
        v.extend_from_slice(&((12 + payload.len()) as u32).to_be_bytes());
        v.extend_from_slice(&seq.to_be_bytes());
        v.extend_from_slice(payload);
        v
    }

    fn send_cmds(&mut self, cmds: Vec<Vec<u8>>) {
        // After a server-side Disconnect there is no point in flooding a dead
        // socket; the wall loop checks disconnect_reason() and stops.
        if self.disconnect.is_some() {
            return;
        }
        let mut pkt = Vec::new();
        pkt.extend_from_slice(&self.peer_id.to_le_bytes());
        pkt.push(0);
        pkt.push(cmds.len() as u8);
        pkt.extend_from_slice(&self.ms().to_be_bytes());
        pkt.extend_from_slice(&self.challenge.to_be_bytes());
        for (i, c) in cmds.iter().enumerate() {
            if c.len() >= 12 && c[2] == 1 {
                let seq = u32::from_be_bytes([c[8], c[9], c[10], c[11]]);
                self.pending.insert(
                    seq,
                    Pending { cmd: c.clone(), at: Instant::now(), tries: 0 },
                );
            }
            pkt.extend_from_slice(c);
            let _ = i;
        }
        if self.debug {
            println!(">> {}", hex::encode_upper(&pkt));
        }
        if let Err(e) = self.sock.send(&pkt) {
            println!("send error: {e}");
        }
    }

    /// Some(reason) if the server closed the connection (e.g. flood kick).
    pub fn disconnect_reason(&self) -> Option<&str> {
        self.disconnect.as_deref()
    }

    fn next_seq(&mut self, ch: u8) -> u32 {
        let v = self.seq.entry(ch).or_insert(0);
        *v += 1;
        *v
    }

    /// CONNECT -> VERIFY (peerId).
    pub fn handshake(host: &str, port: u16) -> io::Result<Photon> {
        let sock = UdpSocket::bind("0.0.0.0:0")?;
        sock.connect((host, port))?;
        sock.set_read_timeout(Some(Duration::from_millis(1200)))?;
        let mut p = Photon {
            sock,
            peer_id: 0xffff,
            challenge: rand::thread_rng().r#gen(),
            t0: Instant::now(),
            seq: HashMap::new(),
            pending: HashMap::new(),
            backlog: Vec::new(),
            last_ping: Instant::now(),
            debug: std::env::var("HYPPER_RUST_DEBUG").is_ok(),
            actor: None,
            disconnect: None,
        };
        let cmd = p.command(T_CONNECT, 255, 1, 1, CONNECT_PAYLOAD);
        p.send_cmds(vec![cmd]);
        for _ in 0..8 {
            for (ctype, payload) in p.pump(1200) {
                if ctype == T_VERIFY && payload.len() >= 2 {
                    p.peer_id = u16::from_le_bytes([payload[0], payload[1]]);
                    return Ok(p);
                }
            }
        }
        Err(io::Error::new(io::ErrorKind::TimedOut, "no VERIFY"))
    }

    pub fn send_op(&mut self, payload: Vec<u8>) {
        let mut full = Vec::with_capacity(payload.len() + 2);
        full.extend_from_slice(&[0xf3, 0x02]);
        full.extend_from_slice(&payload);
        if full.len() <= FRAG_CHUNK {
            let seq = self.next_seq(0);
            let cmd = self.command(T_RELIABLE, 0, 1, seq, &full);
            self.send_cmds(vec![cmd]);
            return;
        }
        let total = full.len();
        let count = total.div_ceil(FRAG_CHUNK);
        let start_seq = *self.seq.get(&0).unwrap_or(&0) + 1;
        for i in 0..count {
            let off = i * FRAG_CHUNK;
            let end = (off + FRAG_CHUNK).min(total);
            let mut frag = Vec::with_capacity(20 + end - off);
            frag.extend_from_slice(&start_seq.to_be_bytes());
            frag.extend_from_slice(&(count as u32).to_be_bytes());
            frag.extend_from_slice(&((i + 1) as u32).to_be_bytes());
            frag.extend_from_slice(&(total as u32).to_be_bytes());
            frag.extend_from_slice(&(off as u32).to_be_bytes());
            frag.extend_from_slice(&full[off..end]);
            let seq = self.next_seq(0);
            let cmd = self.command(T_FRAGMENT, 0, 1, seq, &frag);
            self.send_cmds(vec![cmd]);
        }
    }

    fn ack(&mut self, items: &[(u8, u8, u8, u32, Vec<u8>)], sent_ms: u32) {
        let mut cmds = Vec::new();
        for (ctype, ch, _fl, seq, _pl) in items {
            if *ctype == T_ACK || *ctype == T_PING || *seq == 0 {
                continue;
            }
            let mut pl = Vec::with_capacity(8);
            pl.extend_from_slice(&seq.to_be_bytes());
            pl.extend_from_slice(&sent_ms.to_be_bytes());
            cmds.push(self.command(T_ACK, *ch, 0, 0, &pl));
        }
        if !cmds.is_empty() {
            self.send_cmds(cmds);
        }
    }

    pub fn pump(&mut self, timeout_ms: u64) -> Vec<(u8, Vec<u8>)> {
        let mut raw = [0u8; 65535];
        let mut items: Vec<(u8, u8, u8, u32, Vec<u8>)> = Vec::new();
        let mut out = std::mem::take(&mut self.backlog);
        let mut sent_ms = 0u32;
        if let Ok(n) = self.sock.recv(&mut raw) {
            if self.debug {
                println!("<< {}", hex::encode_upper(&raw[..n]));
            }
            if n >= 12 {
                sent_ms = u32::from_be_bytes([raw[4], raw[5], raw[6], raw[7]]);
                let count = raw[3];
                let mut off = 12usize;
                for _ in 0..count {
                    if off + 12 > n {
                        break;
                    }
                    let ctype = raw[off];
                    let ch = raw[off + 1];
                    let fl = raw[off + 2];
                    let size = u32::from_be_bytes([
                        raw[off + 4],
                        raw[off + 5],
                        raw[off + 6],
                        raw[off + 7],
                    ]) as usize;
                    let seq = u32::from_be_bytes([
                        raw[off + 8],
                        raw[off + 9],
                        raw[off + 10],
                        raw[off + 11],
                    ]);
                    if size < 12 {
                        break;
                    }
                    let end = (off + size).min(n);
                    let payload = raw[off + 12..end].to_vec();
                    items.push((ctype, ch, fl, seq, payload));
                    off += size;
                }
            }
        } else {
            let _ = timeout_ms;
        }
        if items.is_empty() {
            return out;
        }
        self.ack(&items, sent_ms);
        for (ctype, _ch, _fl, seq, payload) in items {
            if ctype == T_ACK {
                if payload.len() >= 4 {
                    let acked = u32::from_be_bytes([payload[0], payload[1], payload[2], payload[3]]);
                    self.pending.remove(&acked);
                }
                continue;
            }
            // Photon command type 4 = Disconnect (the server kicked us).
            if ctype == 4 {
                let code = payload.first().copied().unwrap_or(0);
                self.disconnect = Some(format!(
                    "сервер разорвал соединение (Disconnect, код 0x{code:02X})"
                ));
                continue;
            }
            if ctype == T_VERIFY {
                out.push((T_VERIFY, payload));
                continue;
            }
            if ctype != T_RELIABLE && ctype != T_FRAGMENT {
                continue;
            }
            let _ = seq;
            if payload.len() >= 2 && payload[0] == 0xf3 {
                out.push((payload[1], payload[2..].to_vec()));
            }
        }
        out
    }

    /// Reliable room events observed while servicing ACKs/keepalives.
    pub fn drain_backlog(&mut self) -> Vec<(u8, Vec<u8>)> {
        std::mem::take(&mut self.backlog)
    }

    pub fn retransmit(&mut self) {
        let now = Instant::now();
        let mut again = Vec::new();
        for (_seq, p) in self.pending.iter_mut() {
            if now.duration_since(p.at) < Duration::from_millis(350) {
                continue;
            }
            if p.tries >= 8 {
                continue;
            }
            p.tries += 1;
            p.at = now;
            again.push(p.cmd.clone());
        }
        for c in again {
            self.send_cmds(vec![c]);
        }
    }

    pub fn ping(&mut self) {
        let cmd = self.command(T_PING, 255, 0, 0, &[]);
        self.send_cmds(vec![cmd]);
    }

    pub fn join_lobby(&mut self) {
        let op = build_op(229, &[(213, Val::Str(String::new())), (212, Val::Byte(0))]);
        self.send_op(op);
    }

    /// Authenticate (op 230). Возвращает rc (0 = ок).
    pub fn authenticate(&mut self, uid: &str) -> i32 {
        let op = build_op(
            230,
            &[
                (224, Val::Str(APP_ID.into())),
                (220, Val::Str(APP_VER.into())),
                (223, Val::Str(CLIENT_VER.into())),
                (225, Val::Str(uid.into())),
                (217, Val::Bytes(vec![0])),
                (216, Val::Str(format!("s={}", sign_for(uid)))),
            ],
        );
        self.send_op(op);
        for _ in 0..10 {
            for (mtype, data) in self.pump(900) {
                if mtype == 3 && !data.is_empty() && data[0] == 230 && data.len() >= 3 {
                    return i16::from_le_bytes([data[1], data[2]]) as i32;
                }
            }
        }
        -2
    }

    /// CreateGame (op 227) на мастер-сервере.
    pub fn create_room(
        &mut self,
        name: &str,
        max_players: u8,
        password: &str,
        pvp: bool,
        mode: i32,
        max_props: i32,
        max_vehicles: i32,
        nickname: &str,
    ) -> (i32, String, String) {
        let props = room_props(max_players, password, pvp, mode, max_props, max_vehicles);
        let mut params = vec![
            (255, Val::Str(name.into())),
            (250, Val::Bool(true)),
            (248, props),
            (241, Val::Bool(false)),
            (232, Val::Bool(true)),
            (191, Val::Int(1)),
            (254, Val::Bool(true)),
            (253, Val::Bool(true)),
        ];
        if !nickname.is_empty() {
            params.push((
                249,
                Val::Table(vec![
                    (crate::proto::Key::Byte(255), Val::Str(nickname.into())),
                    (
                        crate::proto::Key::Str("NickName".into()),
                        Val::Str(nickname.into()),
                    ),
                ]),
            ));
        }
        let op = build_op(227, &params);
        self.send_op(op);
        for _ in 0..12 {
            for (mtype, data) in self.pump(1200) {
                if mtype == 4 && !data.is_empty() {
                    if data[0] == 255 && self.actor.is_none() {
                        if let Some(a) = event_actor(&data) {
                            self.actor = Some(a);
                        }
                    }
                    // Preserve join/instantiate events that arrive while the
                    // create response is still being read.
                    self.backlog.push((mtype, data));
                    continue;
                }
                if mtype == 3 && !data.is_empty() && data[0] == 227 && data.len() >= 3 {
                    let rc = i16::from_le_bytes([data[1], data[2]]) as i32;
                    if self.debug {
                        println!("create resp: {}", hex::encode_upper(&data));
                    }
                    let params = parse_params(&data);
                    let mut gs = String::new();
                    let mut token = String::new();
                    for (k, v) in params {
                        if k == 230 {
                            gs = v.clone();
                        }
                        if k == 254 {
                            if let Ok(a) = v.parse::<u32>() {
                                self.actor = Some(a);
                            }
                        }
                        if k == 221 {
                            token = v;
                        }
                    }
                    return (rc, gs, token);
                }
            }
        }
        (-1, String::new(), String::new())
    }
}

pub fn extract_strings(data: &[u8]) -> Vec<String> {
    let mut out = Vec::new();
    let mut p = 0usize;
    while p < data.len() {
        if data[p] == 0x07 {
            p += 1;
            let s = crate::proto::read_string(data, &mut p);
            out.push(s);
        } else if data[p] == 0x03 || data[p] == 0x0b || data[p] == 0x1c || data[p] == 0x1b {
            p += 1;
            if data[p - 1] != 0x1c && data[p - 1] != 0x1b {
                p += 1;
            }
        } else {
            break;
        }
    }
    out
}

/// Пропуск типизированного значения (чтобы дойти до следующего параметра).
fn skip_value(data: &[u8], p: &mut usize, t: u8) {
    match t {
        0x07 => {
            let l = crate::proto::read_varint(data, p) as usize;
            *p = (*p + l).min(data.len());
        }
        0x03 | 0x0b | 0x0c | 0x22 => *p += 1,
        0x0d | 0x0e => *p += 2,
        0x1b | 0x1c | 0x1e | 0x08 | 0x00 => {}
        0x15 => {
            // хештаблица: count + ключи/значения (грубо, до конца не разбираем)
            *p += 1;
        }
        0x47 => {
            let n = crate::proto::read_varint(data, p);
            for _ in 0..n {
                let l = crate::proto::read_varint(data, p) as usize;
                *p = (*p + l).min(data.len());
            }
        }
        0x09 => {
            // zigzag varint
            loop {
                let b = *data.get(*p).unwrap_or(&0);
                *p += 1;
                if b & 0x80 == 0 {
                    break;
                }
            }
        }
        _ => {}
    }
}

/// Параметры ответа операции: [op][rc lo][rc hi][debug value][count][key][type][value]...
pub fn parse_params(data: &[u8]) -> Vec<(u8, String)> {
    let mut out = Vec::new();
    if data.len() < 5 {
        return out;
    }
    let mut p = 3usize;
    let dt = data[p];
    p += 1;
    skip_value(data, &mut p, dt);
    let pc = *data.get(p).unwrap_or(&0);
    p += 1;
    for _ in 0..pc {
        if p + 2 > data.len() {
            break;
        }
        let key = data[p];
        p += 1;
        let t = data[p];
        p += 1;
        let v = match t {
            0x07 => crate::proto::read_string(data, &mut p),
            0x03 => {
                let b = *data.get(p).unwrap_or(&0);
                p += 1;
                b.to_string()
            }
            0x0b | 0x0c => {
                let b = *data.get(p).unwrap_or(&0) as i32;
                p += 1;
                if t == 0x0c {
                    (-b).to_string()
                } else {
                    b.to_string()
                }
            }
            0x0d | 0x0e => {
                let lo = *data.get(p).unwrap_or(&0) as u32;
                let hi = *data.get(p + 1).unwrap_or(&0) as u32;
                p += 2;
                let v = (lo | (hi << 8)) as i32;
                if t == 0x0e {
                    (-v).to_string()
                } else {
                    v.to_string()
                }
            }
            0x09 => {
                // zigzag varint
                let mut shift = 0;
                let mut raw = 0u32;
                loop {
                    let b = *data.get(p).unwrap_or(&0);
                    p += 1;
                    raw |= ((b & 0x7f) as u32) << shift;
                    if b & 0x80 == 0 {
                        break;
                    }
                    shift += 7;
                    if shift > 28 {
                        break;
                    }
                }
                let v = ((raw >> 1) as i32) ^ (-((raw & 1) as i32));
                v.to_string()
            }
            0x1b => "false".into(),
            0x1c => "true".into(),
            0x22 => "0".into(),
            _ => {
                skip_value(data, &mut p, t);
                continue;
            }
        };
        out.push((key, v));
    }
    out
}

impl Photon {
    /// Authenticate на Game Server по токену комнаты (op 230, ключ 221).
    pub fn authenticate_token(&mut self, token: &str) -> i32 {
        let op = build_op(230, &[(221, Val::Str(token.to_string()))]);
        self.send_op(op);
        for _ in 0..10 {
            for (mtype, data) in self.pump(900) {
                if mtype == 3 && !data.is_empty() && data[0] == 230 && data.len() >= 3 {
                    return i16::from_le_bytes([data[1], data[2]]) as i32;
                }
            }
        }
        -2
    }

    /// Ждём событие входа в комнату (event 255) и берём actorNr.
    pub fn wait_in_room(&mut self, timeout_ms: u64) -> Option<u32> {
        let steps = timeout_ms / 200;
        for _ in 0..steps {
            for (mtype, data) in self.pump(200) {
                self.retransmit();
                self.ping();
                if mtype == 4 && !data.is_empty() && data[0] == 255 {
                    let params = parse_params(&[0, 0, 0, 0, 0, data[1], 0]);
                    let _ = params;
                    // параметры события: [count][key][type][value]..., актёра ищем по ключу 254
                    let mut actor = 0u32;
                    let mut p = 1usize;
                    let cnt = *data.get(p).unwrap_or(&0);
                    p += 1;
                    for _ in 0..cnt {
                        if p + 2 > data.len() {
                            break;
                        }
                        let k = data[p];
                        p += 1;
                        let t = data[p];
                        p += 1;
                        if t == 0x0b {
                            let v = *data.get(p).unwrap_or(&0) as u32;
                            p += 1;
                            if k == 254 {
                                actor = v;
                            }
                        } else if t == 0x0d || t == 0x0e {
                            let lo = *data.get(p).unwrap_or(&0) as u32;
                            let hi = *data.get(p + 1).unwrap_or(&0) as u32;
                            p += 2;
                            if k == 254 {
                                actor = lo | (hi << 8);
                            }
                        } else if t == 0x07 {
                            let l = crate::proto::read_varint(&data, &mut p) as usize;
                            p = (p + l).min(data.len());
                        } else if t == 0x1b || t == 0x1c || t == 0x1e || t == 0x22 {
                        } else {
                            break;
                        }
                    }
                    return Some(actor);
                }
            }
        }
        None
    }
}

/// ActorNr из события 255 (Join): параметры идут как [count][key][type][value]...
pub fn event_actor(data: &[u8]) -> Option<u32> {
    event_int(data, 254)
}

/// Integer event parameter (event payload is [eventCode][count][key][type][value]...).
pub fn event_int(data: &[u8], wanted_key: u8) -> Option<u32> {
    if data.len() < 3 {
        return None;
    }
    let mut p = 1usize;
    let cnt = *data.get(p)?;
    p += 1;
    for _ in 0..cnt {
        if p + 2 > data.len() {
            break;
        }
        let k = data[p];
        p += 1;
        let t = data[p];
        p += 1;
        let value = match t {
            0x0b | 0x03 => {
                let v = *data.get(p)? as u32;
                p += 1;
                Some(v)
            }
            0x0c => {
                let v = *data.get(p)? as i32;
                p += 1;
                Some((-v) as u32)
            }
            0x0d | 0x0e => {
                let lo = *data.get(p)? as u32;
                let hi = *data.get(p + 1)? as u32;
                p += 2;
                let v = (lo | (hi << 8)) as i32;
                Some(if t == 0x0e { (-v) as u32 } else { v as u32 })
            }
            0x09 => {
                let mut shift = 0;
                let mut raw = 0u32;
                loop {
                    let b = *data.get(p)?;
                    p += 1;
                    raw |= ((b & 0x7f) as u32) << shift;
                    if b & 0x80 == 0 || shift >= 28 {
                        break;
                    }
                    shift += 7;
                }
                let v = ((raw >> 1) as i32) ^ (-((raw & 1) as i32));
                Some(v as u32)
            }
            0x07 => {
                let l = crate::proto::read_varint(data, &mut p) as usize;
                p = (p + l).min(data.len());
                None
            }
            0x1b | 0x1c | 0x1e | 0x22 => None,
            _ => {
                skip_value(data, &mut p, t);
                None
            }
        };
        if k == wanted_key {
            return value;
        }
    }
    None
}

impl Photon {
    /// Спавн пропа: RaiseEvent 202 (Instantiate) с view id = actor*1000 + sub.
    pub fn spawn_prop(&mut self, name: &str, x: f32, y: f32, z: f32, sub_id: u32) -> u32 {
        let actor = self.actor.unwrap_or(1);
        let view_id = actor * 1000 + sub_id;
        let ts = (std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_millis() as i64)
            .unwrap_or(0)
            % i32::MAX as i64) as i32;
        let ht = crate::proto::monitor_instantiate_ht(
            name, x, y, z, (0.0, 1.0, 0.0, 0.0), view_id, ts,
        );
        let payload = crate::proto::build_raise_event(202, ht, 5);
        self.send_op(payload);
        view_id
    }

    /// Держим соединение: короткий таймаут чтения, пинг каждые ~2 с.
    pub fn keepalive(&mut self, ms: u64) {
        let _ = self
            .sock
            .set_read_timeout(Some(std::time::Duration::from_millis(20)));
        // Always poll at least once. Flooring made keepalive(6) do zero reads,
        // so frame events were never ACKed or retransmitted.
        let steps = ms.div_ceil(20).max(1);
        for _ in 0..steps {
            for (mtype, data) in self.pump(20) {
                if mtype == 4 {
                    self.backlog.push((mtype, data));
                }
            }
            self.retransmit();
        }
        if self.last_ping.elapsed() >= Duration::from_secs(2) {
            self.ping();
            self.last_ping = Instant::now();
        }
    }
}

impl Photon {
    /// Синхронизация содержимого монитора (event 206).
    pub fn monitor_sync(
        &mut self,
        view_id: u32,
        x: f32,
        y: f32,
        z: f32,
        rot: (f32, f32, f32, f32),
        text: &str,
        color: &str,
    ) {
        let payload = monitor_sync_payload(view_id, x, y, z, rot, text, color);
        self.send_op(payload);
    }
}

/// Payload события 206 (Monitor sync) — один в один как
/// build_monitor_sync_payload в ptWorkFreeze.py.
pub fn monitor_sync_payload(
    view_id: u32,
    x: f32,
    y: f32,
    z: f32,
    rot: (f32, f32, f32, f32),
    text: &str,
    color: &str,
) -> Vec<u8> {
    use crate::proto::{build_raise_event_nocache, Val};
    let ts_ms = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis() as i64)
        .unwrap_or(0) as u64;
    // Match ptWorkFreeze.write_compressed_int(): it receives the full epoch
    // millisecond value, then applies a 32-bit zigzag mask.
    let ts_zigzag = ((ts_ms << 1) ^ (ts_ms >> 31)) as u32;
    let vd = Val::Array(vec![
        Val::Int(view_id as i32),
        Val::Bool(false),
        Val::Null,
        Val::Vec3(x, y, z),
        Val::Quat(rot.0, rot.1, rot.2, rot.3),
        Val::Bool(false),
        Val::Bool(true),
        Val::Bool(false),
        Val::Int(0),
        Val::Str(text.to_string()),
        Val::Str(color.to_string()),
    ]);
    let data = Val::Array(vec![Val::CompressedRaw(ts_zigzag), Val::Null, vd]);
    build_raise_event_nocache(206, data)
}
