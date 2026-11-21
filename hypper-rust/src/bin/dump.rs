use hypper_rust::client::monitor_sync_payload;

fn main() {
    let p = monitor_sync_payload(1001, 0.0, 2.0, 15.0, (0.0, 1.0, 0.0, 0.0), "GREEN", "#000000");
    println!("len {}", p.len());
    println!("{}", p[..40.min(p.len())].iter().map(|b| format!("{b:02x}")).collect::<Vec<_>>().join(" "));
    println!("{}", p[p.len()-20..].iter().map(|b| format!("{b:02x}")).collect::<Vec<_>>().join(" "));
}