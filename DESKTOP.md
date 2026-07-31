# Packaging Zenith as a desktop app

This turns the Docker-based Zenith stack into a single installable desktop app
(`.dmg` / `.msi` / `.AppImage`) that launches with a double-click — no
terminal, no `docker compose`. It uses **Tauri** (native OS webview, ~a few MB,
no bundled Chromium) as the shell and a **PyInstaller**-frozen backend as a
Tauri *sidecar* so end users don't need Python.

> **Status: built and verified on Linux (x86_64).** This was compiled
> end-to-end: PyInstaller produced a working 147 MB `zenith-backend` binary
> (boots the real app, `/api/health` → 200), and `tauri build` produced both
> `Zenith_0.1.0_amd64.deb` (~151 MB) and a portable `Zenith_0.1.0_amd64.AppImage`
> (~243 MB), each containing the Tauri shell (links system webkit2gtk — no
> bundled Chromium) and the backend sidecar. **Verified by launching the built
> app: it spawns the sidecar, which binds `127.0.0.1:8420` and serves
> `/api/health` → 200.** Build artifacts are git-ignored (rebuild with the
> steps below). macOS/Windows follow the same steps but haven't been run here —
> expect to iterate on PyInstaller hidden-imports per-platform.
>
> **AppImage tip:** on a host without FUSE (many sandboxes/CI), the AppImage
> bundling step fails with `failed to run linuxdeploy`. Build it with
> `APPIMAGE_EXTRACT_AND_RUN=1 cargo tauri build --bundles appimage`, and run
> the resulting AppImage the same way if FUSE isn't installed.

## How it behaves once built

- **Launch:** a normal app icon. The shell spawns the backend sidecar on
  `127.0.0.1:8420`, then shows the window (the built frontend).
- **Persistence:** the SQLite DB lives in the OS app-data dir
  (`~/Library/Application Support/dev.zenith.app` on macOS,
  `%APPDATA%/dev.zenith.app` on Windows, `~/.local/share/dev.zenith.app` on
  Linux). Closing the app never wipes anything — same persistence model as the
  Docker volume today.
- **Ollama stays external.** Model weights are far too large to bundle; the app
  expects Ollama running on the host (it already detects/reports this on the
  health check). This is the one thing that isn't "double-click and go."

## Prerequisites

- **Rust toolchain** — https://rustup.rs
- **Tauri CLI** — `cargo install tauri-cli --version '^2'` (or `npm i -g @tauri-apps/cli`)
- **Python 3.11 + PyInstaller** — `pip install pyinstaller`
- Platform build deps: see https://tauri.app/start/prerequisites/
  (WebKitGTK on Linux, Xcode CLT on macOS, WebView2 + MSVC on Windows)

## 1. Freeze the backend

```bash
cd backend
pip install -r requirements.txt pyinstaller
pyinstaller zenith-backend.spec
# -> dist/zenith-backend            (Linux/macOS)
# -> dist/zenith-backend.exe        (Windows)
```

Smoke-test the binary before bundling:

```bash
CORTEX_DATA_DIR=/tmp/zenith-test CORTEX_PORT=8420 ./dist/zenith-backend
curl http://127.0.0.1:8420/api/health
```

If it fails to start, it's almost always a missing hidden import from a lazily
loaded dep (faster-whisper/ctranslate2, onnxruntime, av, sqlite-vec). Add it to
`hiddenimports`/`binaries` in `zenith-backend.spec` and rebuild.

## 2. Drop the binary in as a Tauri sidecar

Tauri names sidecars per target triple. Copy the frozen binary in and rename it:

```bash
mkdir -p desktop/src-tauri/binaries
# e.g. on Apple silicon:
cp backend/dist/zenith-backend desktop/src-tauri/binaries/zenith-backend-aarch64-apple-darwin
# Linux x86_64:  zenith-backend-x86_64-unknown-linux-gnu
# Windows:       zenith-backend-x86_64-pc-windows-msvc.exe
```

(Find your triple with `rustc -vV | grep host`.)

## 3. Build the app

```bash
cd desktop/src-tauri
cargo tauri build        # production installer
# or: cargo tauri dev    # runs against the Vite dev server on :5173
```

Output installers land in `desktop/src-tauri/target/release/bundle/`.

## Auto-update

Tauri ships a first-class updater — enable it once there's a release pipeline:

1. Add the updater plugin: `tauri-plugin-updater` (Cargo) + a `plugins.updater`
   block in `tauri.conf.json` with your public key and an `endpoints` URL.
2. Sign releases with `tauri signer generate` / `cargo tauri build --sign`.
3. Host a `latest.json` manifest (GitHub Releases works) that the app polls.

This is intentionally **not** wired up yet — it needs a real release/hosting
pipeline (a place to publish signed builds + the update manifest), which is a
distribution decision, not something meaningful to stub in code. Once you have
a GitHub release flow, the updater is ~20 lines of config on top of this
scaffold.

## macOS note

Unsigned `.dmg`s trip Gatekeeper ("app can't be opened"). For a distributable
build you need an Apple Developer ID cert + notarization
(`cargo tauri build` respects `APPLE_CERTIFICATE`/`APPLE_ID` env vars). For
personal use, right-click → Open once to bypass.
