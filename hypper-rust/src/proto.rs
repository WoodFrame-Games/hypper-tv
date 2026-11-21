//! Protocol18 (Photon) — минимальный набор типов, который нужен клиенту.

use std::collections::BTreeMap;

#[derive(Clone, Debug)]
pub enum Key {
    Byte(u8),
    Str(String),
}

#[derive(Clone, Debug)]
pub enum Val {
    Byte(u8),
    Bool(bool),
    Int(i32),
    /// Protocol18 compressed-int payload already zigzagged by the Python client.
    CompressedRaw(u32),
    Str(String),
    Bytes(Vec<u8>),
    StrArray(Vec<String>),
    Table(Vec<(Key, Val)>),
    Vec3(f32, f32, f32),
    Quat(f32, f32, f32, f32),
    Array(Vec<Val>),
    Dict(Vec<(String, Val)>),
    Float(f32),
    Null,
}

pub struct W(pub Vec<u8>);

impl W {
    pub fn new() -> Self {
        W(Vec::new())
    }

    pub fn varint(&mut self, mut v: u32) {
        while v >= 0x80 {
            self.0.push((v as u8 & 0x7f) | 0x80);
            v >>= 7;
        }
        self.0.push(v as u8);
    }

    /// CompressedInt32 — двухбайтовые варианты little-endian (как читает игра).
    pub fn cint(&mut self, v: i32) {
        if v == 0 {
            self.0.push(0x1e);
        } else if v == -1 {
            self.0.extend_from_slice(&[0x0c, 0x01]);
        } else if v > 0 {
            if v <= 255 {
                self.0.extend_from_slice(&[0x0b, v as u8]);
            } else if v <= 65535 {
                let u = v as u32;
                self.0.push(0x0d);
                self.0.push((u & 0xff) as u8);
                self.0.push((u >> 8) as u8);
            } else {
                self.zigzag(v);
            }
        } else if v >= -255 {
            self.0.extend_from_slice(&[0x0c, (-v) as u8]);
        } else if v >= -65535 {
            let u = (-v) as u32;
            self.0.push(0x0e);
            self.0.push((u & 0xff) as u8);
            self.0.push((u >> 8) as u8);
        } else {
            self.zigzag(v);
        }
    }

    fn zigzag(&mut self, v: i32) {
        self.0.push(0x09);
        let mut z = ((v as u32) << 1) ^ ((v >> 31) as u32);
        while z >= 0x80 {
            self.0.push((z as u8 & 0x7f) | 0x80);
            z >>= 7;
        }
        self.0.push(z as u8);
    }

    pub fn string(&mut self, s: &str) {
        self.0.push(0x07);
        let b = s.as_bytes();
        self.varint(b.len() as u32);
        self.0.extend_from_slice(b);
    }

    pub fn boolean(&mut self, v: bool) {
        self.0.push(if v { 0x1c } else { 0x1b });
    }

    pub fn val(&mut self, v: &Val) {
        match v {
            Val::Byte(b) => {
                self.0.push(0x03);
                self.0.push(*b);
            }
            Val::Bool(b) => self.boolean(*b),
            Val::Int(i) => self.cint(*i),
            Val::CompressedRaw(raw) => {
                self.0.push(0x09);
                self.varint(*raw);
            }
            Val::Str(s) => self.string(s),
            Val::Bytes(b) => {
                if b.len() == 1 {
                    // одиночный байт: 0 -> 0x22, иначе 0x03+значение
                    if b[0] == 0 {
                        self.0.push(0x22);
                    } else {
                        self.0.push(0x03);
                        self.0.push(b[0]);
                    }
                } else {
                    self.0.push(0x79); // byte[]
                    self.varint(b.len() as u32);
                    self.0.extend_from_slice(b);
                }
            }
            Val::StrArray(a) => {
                self.0.push(0x47);
                self.varint(a.len() as u32);
                for s in a {
                    let raw = s.as_bytes();
                    self.varint(raw.len() as u32);
                    self.0.extend_from_slice(raw);
                }
            }
            Val::Null => self.0.push(0x08),
            Val::Float(f) => {
                self.0.push(0x05);
                self.0.extend_from_slice(&f.to_be_bytes());
            }
            Val::Vec3(x, y, z) => {
                self.0.push(0xd6);
                self.0.push(12);
                self.0.extend_from_slice(&x.to_be_bytes());
                self.0.extend_from_slice(&y.to_be_bytes());
                self.0.extend_from_slice(&z.to_be_bytes());
            }
            Val::Quat(w, x, y, z) => {
                self.0.push(0xd1);
                self.0.push(16);
                self.0.extend_from_slice(&w.to_be_bytes());
                self.0.extend_from_slice(&x.to_be_bytes());
                self.0.extend_from_slice(&y.to_be_bytes());
                self.0.extend_from_slice(&z.to_be_bytes());
            }
            Val::Array(items) => {
                self.0.push(0x17);
                self.varint(items.len() as u32);
                for it in items {
                    self.val(it);
                }
            }
            Val::Dict(items) => {
                self.0.extend_from_slice(&[0x14, 0x07, 0x00]);
                self.varint(items.len() as u32);
                for (k, v) in items {
                    let raw = k.as_bytes();
                    self.varint(raw.len() as u32);
                    self.0.extend_from_slice(raw);
                    self.val(v);
                }
            }
            Val::Table(entries) => {
                self.0.push(0x15);
                self.varint(entries.len() as u32);
                for (k, v) in entries {
                    self.key(k);
                    self.val(v);
                }
            }
        }
    }

    fn key(&mut self, k: &Key) {
        match k {
            Key::Byte(b) => {
                self.0.push(0x03);
                self.0.push(*b);
            }
            Key::Str(s) => self.string(s),
        }
    }
}

/// Operation request: F3 02 <opCode> <paramCount> <params...>
pub fn build_op(code: u8, params: &[(u8, Val)]) -> Vec<u8> {
    let mut w = W::new();
    w.0.push(code);
    w.0.push(params.len() as u8);
    for (k, v) in params {
        w.0.push(*k);
        w.val(v);
    }
    w.0
}

/// Хештаблица свойств комнаты (MaxProps/MaxVehicles/режим и т.д.).
pub fn room_props(
    max_players: u8,
    password: &str,
    pvp: bool,
    gamemode: i32,
    max_props: i32,
    max_vehicles: i32,
) -> Val {
    let mut lobby = vec![
        "Map".to_string(),
        "GameMode".to_string(),
        "PvP".to_string(),
        "Nextbot".to_string(),
        "PublicMechanism".to_string(),
    ];
    if !password.is_empty() {
        lobby.push("Password".to_string());
    }
    let mut e: Vec<(Key, Val)> = Vec::new();
    e.push((Key::Byte(255), Val::Byte(max_players)));
    e.push((Key::Byte(243), Val::Int(max_players as i32)));
    e.push((Key::Byte(254), Val::Bool(true)));
    e.push((Key::Byte(253), Val::Bool(true)));
    e.push((Key::Byte(250), Val::StrArray(lobby)));
    e.push((Key::Str("Map".into()), Val::Str("FlatGrass".into())));
    e.push((Key::Str("GameMode".into()), Val::Int(gamemode)));
    if !password.is_empty() {
        e.push((Key::Str("Password".into()), Val::Str(password.into())));
    }
    e.push((Key::Str("MaxProps".into()), Val::Int(max_props)));
    e.push((Key::Str("PropsCount".into()), Val::Int(0)));
    e.push((Key::Str("MaxVehicles".into()), Val::Int(max_vehicles)));
    e.push((Key::Str("VehiclesCount".into()), Val::Int(0)));
    e.push((Key::Str("PvP".into()), Val::Bool(pvp)));
    e.push((Key::Str("RPG".into()), Val::Bool(false)));
    e.push((Key::Str("PublicMechanism".into()), Val::Bool(true)));
    e.push((Key::Str("Nextbot".into()), Val::Bool(false)));
    e.push((Key::Str("OnlyModUsers".into()), Val::Bool(false)));
    Val::Table(e)
}

/// Разбор хештаблицы ответа/события (нам нужны строки и числа).
pub fn parse_table(data: &[u8]) -> BTreeMap<String, String> {
    let mut out = BTreeMap::new();
    if data.len() < 2 || data[0] != 0x15 {
        return out;
    }
    let mut p = 1usize;
    let cnt = read_varint(data, &mut p);
    for _ in 0..cnt {
        // ключ
        let kt = *data.get(p).unwrap_or(&0);
        p += 1;
        let key = if kt == 0x03 {
            let k = *data.get(p).unwrap_or(&0);
            p += 1;
            k.to_string()
        } else if kt == 0x07 {
            read_string(data, &mut p)
        } else {
            break;
        };
        // значение
        let vt = *data.get(p).unwrap_or(&0);
        p += 1;
        let val = match vt {
            0x07 => read_string(data, &mut p),
            0x0b => {
                let v = *data.get(p).unwrap_or(&0) as i32;
                p += 1;
                v.to_string()
            }
            0x0c => {
                let v = *data.get(p).unwrap_or(&0) as i32;
                p += 1;
                (-v).to_string()
            }
            0x0d | 0x0e => {
                let lo = *data.get(p).unwrap_or(&0) as u32;
                let hi = *data.get(p + 1).unwrap_or(&0) as u32;
                p += 2;
                let v = (lo | (hi << 8)) as i32;
                if vt == 0x0e { (-v).to_string() } else { v.to_string() }
            }
            0x1c => "true".into(),
            0x1b => "false".into(),
            0x1e => "0".into(),
            _ => {
                // не разбираем дальше — структура неизвестной длины
                break;
            }
        };
        out.insert(key, val);
    }
    out
}

pub fn read_varint(d: &[u8], p: &mut usize) -> u32 {
    let mut shift = 0;
    let mut v = 0u32;
    loop {
        let b = *d.get(*p).unwrap_or(&0);
        *p += 1;
        v |= ((b & 0x7f) as u32) << shift;
        if b & 0x80 == 0 {
            break;
        }
        shift += 7;
        if shift > 28 {
            break;
        }
    }
    v
}

pub fn read_string(d: &[u8], p: &mut usize) -> String {
    let n = read_varint(d, p) as usize;
    let end = (*p + n).min(d.len());
    let s = String::from_utf8_lossy(&d[*p..end]).to_string();
    *p = end;
    s
}
/// RaiseEvent (op 253): Code + Data (без Cache).
pub fn build_raise_event_nocache(code: u8, data: Val) -> Vec<u8> {
    let mut w = W::new();
    w.0.extend_from_slice(&[253, 2, 244, 0x03, code, 245]);
    w.val(&data);
    w.0
}

/// RaiseEvent (op 253): Code + Data + Cache.
pub fn build_raise_event(code: u8, data: Val, cache: u8) -> Vec<u8> {
    let mut w = W::new();
    w.0.extend_from_slice(&[253, 3, 244, 0x03, code, 245]);
    w.val(&data);
    w.0.extend_from_slice(&[247, 0x03, cache]);
    w.0
}

/// Instantiate-событие для одного монитора (как в load_save_from_file).
pub fn monitor_instantiate_ht(
    name: &str,
    x: f32,
    y: f32,
    z: f32,
    rot: (f32, f32, f32, f32),
    view_id: u32,
    ts: i32,
) -> Val {
    Val::Table(vec![
        (Key::Byte(0), Val::Str(name.to_string())),
        (Key::Byte(1), Val::Vec3(x, y, z)),
        (Key::Byte(2), Val::Quat(rot.0, rot.1, rot.2, rot.3)),
        (Key::Byte(6), Val::Int(ts)),
        (Key::Byte(7), Val::Int(view_id as i32)),
    ])
}
