mod args;
mod core;
mod gui;
mod video;

fn main() {
    let argv: Vec<String> = std::env::args().collect();
    let cli = argv.iter().any(|a| a == "--cli" || a == "--help" || a == "-h");
    if cli {
        match args::parse() {
            Ok(Some(cfg)) => {
                if let Err(e) = core::run(cfg) {
                    eprintln!("error: {e}");
                    std::process::exit(1);
                }
            }
            Ok(None) => {}
            Err(e) => {
                eprintln!("error: {e}");
                std::process::exit(2);
            }
        }
        return;
    }
    if let Err(e) = gui::run_gui() {
        eprintln!("gui error: {e}");
        std::process::exit(1);
    }
}
