// Zenith desktop shell (Tauri v2).
//
// Responsibilities:
//   1. Spawn the frozen Python backend (PyInstaller sidecar) on startup,
//      pointing it at the platform's app-data directory so conversations
//      persist across restarts exactly like the Docker deployment.
//   2. Show the window, which loads the built frontend; the frontend talks to
//      the sidecar at http://127.0.0.1:8420 (its default VITE_API_BASE).
//   3. Kill the backend when the app quits so no orphan process lingers.
//   4. System tray icon (Show/Hide, Quit) so the app can live in the
//      background instead of only existing as a taskbar window.
//   5. A global hotkey (Ctrl/Cmd+Shift+Z) that toggles the main window's
//      visibility from anywhere on the OS — "summon Zenith" without
//      alt-tabbing to find it.
//
// This is a reference scaffold — it has NOT been compiled in the environment
// it was written in (no Rust toolchain there). Build per DESKTOP.md.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri::menu::{Menu, MenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::Manager;
use tauri_plugin_global_shortcut::{GlobalShortcutExt, Shortcut, ShortcutState};
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;
use std::sync::Mutex;

// Holds the running backend child so we can kill it on exit.
struct Backend(Mutex<Option<CommandChild>>);

fn toggle_main_window(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let visible = window.is_visible().unwrap_or(false);
        if visible {
            let _ = window.hide();
        } else {
            let _ = window.show();
            let _ = window.set_focus();
        }
    }
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .manage(Backend(Mutex::new(None)))
        .setup(|app| {
            // App-data dir: ~/Library/Application Support/dev.zenith.desktop (macOS),
            // %APPDATA%/dev.zenith.desktop (Windows), ~/.local/share/dev.zenith.desktop (Linux).
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

            // --- System tray ---
            let show_item = MenuItem::with_id(app, "show", "Show Zenith", true, None::<&str>)?;
            let quit_item = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let tray_menu = Menu::with_items(app, &[&show_item, &quit_item])?;

            TrayIconBuilder::new()
                .icon(app.default_window_icon().unwrap().clone())
                .menu(&tray_menu)
                .show_menu_on_left_click(true)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "show" => toggle_main_window(app),
                    "quit" => app.exit(0),
                    _ => {}
                })
                .build(app)?;

            // --- Global hotkey: Ctrl/Cmd+Shift+Z toggles the window ---
            let shortcut: Shortcut = "CmdOrCtrl+Shift+Z".parse().expect("invalid shortcut spec");
            let app_handle = app.handle().clone();
            app.global_shortcut().on_shortcut(shortcut, move |_app, _shortcut, event| {
                if event.state() == ShortcutState::Pressed {
                    toggle_main_window(&app_handle);
                }
            })?;

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
        .expect("error while running Zenith");
}
