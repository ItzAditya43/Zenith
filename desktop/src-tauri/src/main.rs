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
//   6. Auto-update: checks GitHub Releases quietly at startup and from the
//      tray's "Check for Updates…". When there's a new version it asks;
//      on yes it downloads, verifies the signature, installs and restarts.
//   7. The desktop popout (Quickbar) — see create_quickbar().
//
// This is a reference scaffold — it has NOT been compiled in the environment
// it was written in (no Rust toolchain there). Build per DESKTOP.md.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri::menu::{Menu, MenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, Shortcut, ShortcutState};
use tauri_plugin_opener::OpenerExt;
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;
use tauri_plugin_updater::UpdaterExt;
use std::sync::Mutex;

// Holds the running backend child so we can kill it on exit.
struct Backend(Mutex<Option<CommandChild>>);

// User-initiated, read-only screenshot capture for the composer's
// "attach screenshot" button (ScreenshotButton.jsx). Captures the primary
// screen and returns it as a base64 PNG data URL — no temp file to clean up,
// no synthetic input, nothing automated or hidden. This is deliberately NOT
// the OS-level "computer-use" surface rejected in docs/NOT_BUILT.md: it only
// fires on an explicit user click and never simulates mouse/keyboard input.
#[tauri::command]
fn capture_screenshot() -> Result<String, String> {
    use screenshots::Screen;

    let screens = Screen::all().map_err(|e| format!("couldn't list screens: {e}"))?;
    let screen = screens
        .into_iter()
        .next()
        .ok_or_else(|| "no screen found to capture".to_string())?;

    let image = screen
        .capture()
        .map_err(|e| format!("screen capture failed: {e}"))?;

    let mut png_bytes: Vec<u8> = Vec::new();
    {
        let mut cursor = std::io::Cursor::new(&mut png_bytes);
        image
            .write_to(&mut cursor, screenshots::image::ImageFormat::Png)
            .map_err(|e| format!("couldn't encode screenshot as PNG: {e}"))?;
    }

    use base64::Engine;
    let encoded = base64::engine::general_purpose::STANDARD.encode(&png_bytes);
    Ok(format!("data:image/png;base64,{encoded}"))
}

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

// The desktop popout (frontend route #/quickbar). On Hyprland it's created
// visible and a window rule parks it on the `special:zenith` workspace, so
// Super+Space (togglespecialworkspace zenith) shows and hides it instantly
// with no process spawn. Elsewhere it starts hidden and Ctrl+Alt+Space
// toggles it.
fn on_hyprland() -> bool {
    std::env::var("HYPRLAND_INSTANCE_SIGNATURE").is_ok()
}

fn create_quickbar(app: &tauri::AppHandle) -> tauri::Result<()> {
    if app.get_webview_window("quickbar").is_some() {
        return Ok(());
    }
    let builder = WebviewWindowBuilder::new(app, "quickbar", WebviewUrl::App("index.html#/quickbar".into()))
        .title("Zenith Quickbar")
        .inner_size(760.0, 460.0)
        .decorations(false)
        .always_on_top(true)
        .skip_taskbar(true)
        .resizable(false)
        .center()
        .visible(on_hyprland());
    // Transparent windows on macOS need Tauri's private-API feature (which
    // also bars the App Store); there the popout simply has a solid background.
    #[cfg(not(target_os = "macos"))]
    let builder = builder.transparent(true);
    builder.build()?;
    Ok(())
}

fn toggle_quickbar(app: &tauri::AppHandle) {
    if create_quickbar(app).is_err() {
        return;
    }
    if let Some(w) = app.get_webview_window("quickbar") {
        if w.is_visible().unwrap_or(false) {
            let _ = w.hide();
        } else {
            let _ = w.show();
            let _ = w.set_focus();
        }
    }
}

// Updates come from GitHub Releases (latest.json, signed with the key in
// DESKTOP.md). `interactive` = the tray item: say "up to date" or show the
// error. The quiet startup check only speaks up when there's an update.
// Installing asks first, then downloads, verifies the signature, replaces
// the app (the AppImage, MSI/NSIS installer or .app) and restarts.
fn check_for_updates(app: tauri::AppHandle, interactive: bool) {
    tauri::async_runtime::spawn(async move {
        let updater = match app.updater() {
            Ok(u) => u,
            Err(e) => {
                if interactive {
                    app.dialog().message(format!("Couldn't check for updates: {e}")).show(|_| {});
                }
                return;
            }
        };
        match updater.check().await {
            Ok(Some(update)) => {
                let version = update.version.clone();
                let notes = update.body.clone().unwrap_or_default();
                let summary: String = notes.lines().take(8).collect::<Vec<_>>().join("\n");
                let handle = app.clone();
                app.dialog()
                    .message(format!(
                        "Zenith {version} is available.\n\n{summary}\n\nInstall it now? Zenith restarts when it's done."
                    ))
                    .title("Update available")
                    .buttons(MessageDialogButtons::OkCancelCustom("Install and restart".into(), "Later".into()))
                    .show(move |install| {
                        if !install {
                            return;
                        }
                        tauri::async_runtime::spawn(async move {
                            match update.download_and_install(|_, _| {}, || {}).await {
                                Ok(()) => handle.restart(),
                                Err(e) => {
                                    handle
                                        .dialog()
                                        .message(format!("The update couldn't be installed: {e}\n\nYou can download it from the Releases page instead."))
                                        .title("Update failed")
                                        .show(|_| {});
                                    let _ = handle.opener().open_url(
                                        "https://github.com/ItzAditya43/Zenith/releases/latest",
                                        None::<&str>,
                                    );
                                }
                            }
                        });
                    });
            }
            Ok(None) => {
                if interactive {
                    app.dialog().message("You're on the latest version.").title("Up to date").show(|_| {});
                }
            }
            Err(e) => {
                if interactive {
                    app.dialog().message(format!("Couldn't check for updates: {e}")).show(|_| {});
                }
            }
        }
    });
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_opener::init())
        .manage(Backend(Mutex::new(None)))
        .invoke_handler(tauri::generate_handler![capture_screenshot])
        .setup(|app| {
            #[cfg(target_os = "linux")]
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.with_webview(|wv| {
                    use webkit2gtk::{PermissionRequestExt, SettingsExt, WebViewExt};
                    let view = wv.inner();
                    if let Some(settings) = view.settings() {
                        settings.set_enable_media_stream(true);
                        settings.set_enable_mediasource(true);
                    }
                    // Only the app's own pages load here, so grant mic requests;
                    // the OS still decides whether a device is available.
                    view.connect_permission_request(|_, req| {
                        req.allow();
                        true
                    });
                });
            }
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
                .sidecar("zenith-backend")
                .expect("zenith-backend sidecar missing")
                .env("ZENITH_DATA_DIR", data_dir)
                .env("ZENITH_PORT", "8420")
                .env("ZENITH_BIND", "127.0.0.1");

            let (_rx, child) = sidecar.spawn().expect("failed to start backend");
            app.state::<Backend>().0.lock().unwrap().replace(child);

            // --- System tray ---
            let show_item = MenuItem::with_id(app, "show", "Show Zenith", true, None::<&str>)?;
            let update_item = MenuItem::with_id(app, "check_update", "Check for Updates…", true, None::<&str>)?;
            let quit_item = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let tray_menu = Menu::with_items(app, &[&show_item, &update_item, &quit_item])?;

            TrayIconBuilder::new()
                .icon(app.default_window_icon().unwrap().clone())
                .menu(&tray_menu)
                .show_menu_on_left_click(true)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "show" => toggle_main_window(app),
                    "check_update" => check_for_updates(app.clone(), true),
                    "quit" => app.exit(0),
                    _ => {}
                })
                .build(app)?;

            // --- Quiet update check shortly after start ---
            let upd_handle = app.handle().clone();
            std::thread::spawn(move || {
                std::thread::sleep(std::time::Duration::from_secs(20));
                check_for_updates(upd_handle, false);
            });

            // --- Desktop popout ---
            create_quickbar(app.handle())?;
            if !on_hyprland() {
                let qb_shortcut: Shortcut = "CmdOrCtrl+Alt+Space".parse().expect("invalid shortcut spec");
                let qb_handle = app.handle().clone();
                app.global_shortcut().on_shortcut(qb_shortcut, move |_app, _shortcut, event| {
                    if event.state() == ShortcutState::Pressed {
                        toggle_quickbar(&qb_handle);
                    }
                })?;
            }

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
