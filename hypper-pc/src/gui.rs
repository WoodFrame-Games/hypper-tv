use std::sync::atomic::Ordering;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use eframe::egui;

use crate::args::Config;
use crate::core;

pub fn run_gui() -> eframe::Result<()> {
    let opts = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default().with_inner_size([820.0, 660.0]),
        ..Default::default()
    };
    eframe::run_native(
        "Hypper TV (PC)",
        opts,
        Box::new(|cc| Ok(Box::new(App::new(cc)))),
    )
}

fn wide(ui: &mut egui::Ui, v: &mut String, hint: &str) {
    ui.add(
        egui::TextEdit::singleline(v)
            .hint_text(hint)
            .desired_width(f32::INFINITY),
    );
}

struct App {
    cfg: Config,
    seconds_text: String,
    logs: Arc<Mutex<Vec<String>>>,
    running: Arc<Mutex<bool>>,
}

impl App {
    fn new(_cc: &eframe::CreationContext<'_>) -> Self {
        let logs = Arc::new(Mutex::new(Vec::new()));
        let sink = logs.clone();
        core::set_logger(move |line| {
            if let Ok(mut v) = sink.lock() {
                v.push(line);
                if v.len() > 2000 {
                    v.remove(0);
                }
            }
        });
        Self {
            cfg: Config::default(),
            seconds_text: String::new(),
            logs,
            running: Arc::new(Mutex::new(false)),
        }
    }
}

impl eframe::App for App {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        ctx.request_repaint_after(Duration::from_millis(250));
        let running = *self.running.lock().unwrap();
        egui::TopBottomPanel::top("form").show(ctx, |ui| {
            ui.label("Комната");
            wide(ui, &mut self.cfg.room, "HypperTV");
            ui.label("Пароль");
            wide(ui, &mut self.cfg.password, "");
            ui.label("Видео (путь или URL)");
            wide(ui, &mut self.cfg.url, "C:\\video.mp4 или https://...");
            ui.add_space(6.0);
            egui::Grid::new("grid").num_columns(3).spacing([10.0, 6.0]).show(ui, |ui| {
                ui.label("Колонки");
                ui.add(egui::DragValue::new(&mut self.cfg.cols).range(1..=64));
                ui.label("");
                ui.end_row();
                ui.label("Ряды");
                ui.add(egui::DragValue::new(&mut self.cfg.rows).range(1..=25));
                ui.label("");
                ui.end_row();
                ui.label("Пиксели X на монитор");
                ui.add(egui::DragValue::new(&mut self.cfg.cell_w).range(1..=64));
                ui.label("");
                ui.end_row();
                ui.label("Пиксели Y на монитор");
                ui.add(egui::DragValue::new(&mut self.cfg.cell_h).range(1..=48));
                ui.label("");
                ui.end_row();
                ui.label("Размер текста, %");
                ui.add(egui::DragValue::new(&mut self.cfg.size).range(10..=200));
                ui.label("");
                ui.end_row();
                ui.label("Кадров/с");
                ui.add(egui::DragValue::new(&mut self.cfg.fps).speed(0.5).range(0.5..=30.0));
                ui.label("");
                ui.end_row();
                ui.label("Секунд (пусто = до конца видео)");
                ui.add(egui::TextEdit::singleline(&mut self.seconds_text).desired_width(70.0));
                ui.label("");
                ui.end_row();
                ui.label("Зациклить видео");
                ui.checkbox(&mut self.cfg.loop_input, "");
                ui.label("");
                ui.end_row();
            });
            ui.add_space(6.0);
            ui.label("ffmpeg");
            wide(ui, &mut self.cfg.ffmpeg, "ffmpeg");
            ui.horizontal(|ui| {
                if !running && ui.button("Старт").clicked() {
                    self.start();
                }
                if running && ui.button("Стоп").clicked() {
                    core::STOP.store(true, Ordering::Relaxed);
                }
                ui.label(if running { "работает" } else { "остановлено" });
            });
        });
        egui::CentralPanel::default().show(ctx, |ui| {
            ui.label("Журнал");
            egui::ScrollArea::vertical().stick_to_bottom(true).show(ui, |ui| {
                if let Ok(v) = self.logs.lock() {
                    for line in v.iter() {
                        ui.monospace(line);
                    }
                }
            });
        });
    }
}

impl App {
    fn start(&mut self) {
        core::STOP.store(false, Ordering::Relaxed);
        self.cfg.seconds = self.seconds_text.trim().parse::<u64>().ok();
        *self.running.lock().unwrap() = true;
        let cfg = self.cfg.clone();
        let running = self.running.clone();
        std::thread::spawn(move || {
            let res = core::run(cfg);
            core::emit(match res {
                Ok(()) => "готово".to_string(),
                Err(e) => format!("ошибка: {e}"),
            });
            *running.lock().unwrap() = false;
        });
    }
}
