# Packaging Zenith as a desktop app

This turns the Docker-based Zenith stack into a single installable desktop app
(`.dmg` / `.msi` / `.AppImage`) that launches with a double-click — no
terminal, no `docker compose`. It uses **Tauri** (native OS webview, ~a few MB,
no bundled Chromium) as the shell and a **PyInstaller**-frozen backend as a
Tauri *sidecar* so end users don't need Python.

> **Status: built and verified on Linux (x86_64).** This was compiled
> end-to-end: PyInstaller produced a working 147 MB `cortex-backend` binary
> (boots the real app, `/api/health` → 200), and `tauri build` produced both
> `Zenith_0.1.0_amd64.deb` (~151 MB) and a portable `Zenith_0.1.0_amd64.AppImage`
> (~243 MB), each containing the Tauri shell (links system webkit2gtk — no
> bundled Chromium) and the backend sidecar. **Verified by launching the built
> app: it spawns the sidecar, which binds `127.0.0.1:8420` and serves
> `/api/health` → 200.** Build artifacts are git-ignored (rebuild with the
> steps below). **Windows is built by CI** (`.github/workflows/ci.yml`,
> `desktop-windows` job) on every push — PyInstaller freezes the backend to
> `cortex-backend.exe`, then `cargo tauri build` produces the `.msi`/`.exe`
> installers as uploaded artifacts; this hasn't been run on physical Windows
> hardware, just GitHub's `windows-latest` runner. macOS hasn't been
> attempted — expect to iterate on PyInstaller hidden-imports if you do.
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
pyinstaller cortex-backend.spec
# -> dist/cortex-backend            (Linux/macOS)
# -> dist/cortex-backend.exe        (Windows)
```

Smoke-test the binary before bundling:

```bash
CORTEX_DATA_DIR=/tmp/zenith-test CORTEX_PORT=8420 ./dist/cortex-backend
curl http://127.0.0.1:8420/api/health
```

If it fails to start, it's almost always a missing hidden import from a lazily
loaded dep (faster-whisper/ctranslate2, onnxruntime, av, sqlite-vec). Add it to
`hiddenimports`/`binaries` in `cortex-backend.spec` and rebuild.

## 2. Drop the binary in as a Tauri sidecar

Tauri names sidecars per target triple. Copy the frozen binary in and rename it:

```bash
mkdir -p desktop/src-tauri/binaries
# e.g. on Apple silicon:
cp backend/dist/cortex-backend desktop/src-tauri/binaries/cortex-backend-aarch64-apple-darwin
# Linux x86_64:  cortex-backend-x86_64-unknown-linux-gnu
# Windows:       cortex-backend-x86_64-pc-windows-msvc.exe
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

**Status: wired up.** `tauri-plugin-updater` is registered in `main.rs`, with
a system-tray **"Check for Updates…"** item that checks GitHub Releases and
shows a native dialog either way (update found, or already current). Clicking
it does **not** auto-download-and-install — that's a bigger trust step
(silently replacing the running binary) than could be verified end-to-end
without a real published release to test against; the checked-and-tell-you
half is the verified-safe subset. Wiring the in-app install step is a
reasonable follow-up once a release has actually shipped once.

**The release pipeline** (`.github/workflows/release.yml`) builds and
publishes signed Windows + Linux + macOS installers whenever a `v*` tag is
pushed (e.g. `git tag v0.2.0 && git push --tags`), using
[`tauri-apps/tauri-action`](https://github.com/tauri-apps/tauri-action) to
freeze the backend, build the installer, sign it, and generate the
`latest.json` manifest the updater plugin polls — all as a **draft** GitHub
Release, so nothing goes public until you review and publish it manually.

**The signing keypair** was generated once via `tauri signer generate`. The
public half lives in `tauri.conf.json`'s `plugins.updater.pubkey` (public
keys are meant to be committed). The private half is **not** in the repo or
on disk anywhere — it exists only as the `TAURI_SIGNING_PRIVATE_KEY` /
`TAURI_SIGNING_PRIVATE_KEY_PASSWORD` GitHub Actions secrets on this repo,
set directly via `gh secret set` and never displayed or logged. If you ever
need to rotate it: `npx tauri signer generate -w /tmp/new-key.pem`, update
the `pubkey` in `tauri.conf.json`, then `gh secret set TAURI_SIGNING_PRIVATE_KEY
< /tmp/new-key.pem` and delete the local file — the same pattern, not
something to improvise differently.

## macOS note

The release workflow now builds a macOS installer on every tagged release
(`macos-latest` runner, same freeze-sidecar-then-`tauri-action` steps as
Windows/Linux) — but it is **unsigned/unnotarized** unless you set the Apple
certificate/notarization secrets below, and it has not been run against a
real tag as of this writing (i.e. built in CI, not yet hand-verified on
actual macOS hardware the way the Linux build has been — see the top-level
README's Known Limitations). Unsigned `.dmg`s trip Gatekeeper ("app can't be
opened"). For a distributable build you need an Apple Developer ID cert + notarization
(`cargo tauri build` respects `APPLE_CERTIFICATE`/`APPLE_ID` env vars). For
personal use, right-click → Open once to bypass.
