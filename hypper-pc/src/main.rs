mod args;
mod core;
mod video;

fn main() {
    let cfg = match args::parse() {
        Ok(Some(cfg)) => cfg,
        Ok(None) => return,
        Err(e) => {
            eprintln!("error: {e}");
            std::process::exit(2);
        }
    };
    if let Err(e) = core::run(cfg) {
        eprintln!("error: {e}");
        std::process::exit(1);
    }
}
