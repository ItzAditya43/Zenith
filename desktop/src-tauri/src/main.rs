// Cortex desktop shell (Tauri v2).
//
// Responsibilities:
//   1. Spawn the frozen Python backend (PyInstaller sidecar) on startup,
//      pointing it at the platform's app-data directory so conversations
//      persist across restarts exactly like the Docker deployment.
//   2. Show the window, which loads the built frontend; the frontend talks to
//      the sidecar at http://127.0.0.1:8420 (its default VITE_API_BASE).
//   3. Kill the backend when the app quits so no orphan process lingers.
//
// This is a reference scaffold — it has NOT been compiled in the environment
// it was written in (no Rust toolchain there). Build per DESKTOP.md.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri::Manager;
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;
use std::sync::Mutex;

// Holds the running backend child so we can kill it on exit.
struct Backend(Mutex<Option<CommandChild>>);

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(Backend(Mutex::new(None)))
        .setup(|app| {
            // App-data dir: ~/Library/Application Support/dev.cortex.app (macOS),
            // %APPDATA%/dev.cortex.app (Windows), ~/.local/share/dev.cortex.app (Linux).
            let data_dir = app
                .path()
                .app_data_dir()
                .expect("no app data dir")
                .to_string_lossy()
                .to_string();

            let sidecar = app
                .shell()
                .sidecar("cortex-backend")
                .expect("cortex-backend sidecar missing")
                .env("CORTEX_DATA_DIR", data_dir)
                .env("CORTEX_PORT", "8420")
                .env("CORTEX_BIND", "127.0.0.1");

            let (_rx, child) = sidecar.spawn().expect("failed to start backend");
            app.state::<Backend>().0.lock().unwrap().replace(child);
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                if let Some(child) = window.state::<Backend>().0.lock().unwrap().take() {
                    let _ = child.kill();
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running Cortex");
}
