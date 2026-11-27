# Where Zenith is known to work

This is filled in from real runs, not hopes. If you run Zenith somewhere not
listed (or something listed breaks), please [open an issue](https://github.com/ItzAditya43/Zenith/issues)
with your OS, GPU, Ollama version and what you tried — that's how this table grows.

## Verified by hand

| OS | Install | GPU / RAM | Ollama | What was checked |
|---|---|---|---|---|
| EndeavourOS (Arch), kernel 7.2, Hyprland (Wayland) | Desktop AppImage, and from source | NVIDIA RTX 3050 Laptop 4 GB · 15 GB RAM | 0.21.2 | Chat, agent tasks (background and live), code workspace, memory, research, workflows, model comparison, desktop control popout, providers (Ollama's OpenAI API), in-app updates |

Notes from that machine: 1–3B models answer quickly; a 3B vision model
(`qwen2.5vl:3b`) can be too slow on 4 GB of VRAM and gets stopped by the
stall watchdog — screenshots still work there because Zenith reads their
text with OCR first.

## Built and checked automatically (CI), not yet run by a person

| Target | What CI does on every push / release |
|---|---|
| Windows x64 | Freezes the backend, smoke-tests it (`/api/health`), builds `.msi` and `.exe` installers |
| macOS (Apple silicon) | Compiles the desktop app on every push; the release builds a `.dmg` |
| Linux x86_64 | Release builds `.AppImage`, `.deb`, `.rpm` |
| Docker (amd64, arm64) | Release publishes backend and frontend images to GHCR |
| Backend | ruff, mypy, 520+ tests with coverage, dependency audit |
| Frontend | lint, type check, unit tests, end-to-end tests in a browser |

## Signing

| Platform | Status | To turn it on |
|---|---|---|
| Linux | AppImage/deb/rpm are signed for the in-app updater | Already on |
| macOS | Not notarized — first launch needs right-click → Open | Add `APPLE_CERTIFICATE`, `APPLE_CERTIFICATE_PASSWORD`, `APPLE_SIGNING_IDENTITY`, `APPLE_ID`, `APPLE_PASSWORD` (app-specific), `APPLE_TEAM_ID` as repo secrets; the release workflow signs and notarizes when they exist |
| Windows | Unsigned — SmartScreen warns on first run | Add `WINDOWS_CERTIFICATE` (base64 `.pfx`) and `WINDOWS_CERTIFICATE_PASSWORD`; the release signs with `signtool` when they exist. This path hasn't been run with a real certificate yet. |

## Where your data lives

Everything Zenith knows is in one folder: the database (`zenith.db`), settings (`config.json`), attachments (`uploads/`) and the log (`zenith.log`, rotated at 2 MB, 3 kept).

| Install | Folder |
|---|---|
| Desktop app, Linux | `~/.local/share/<app id>/` |
| Desktop app, macOS | `~/Library/Application Support/<app id>/` |
| Desktop app, Windows | `%APPDATA%\<app id>\` |
| From source | `backend/data/` (or `$ZENITH_DATA_DIR`) |
| Docker | the volume mounted at `/data` |

`<app id>` is `dev.zenith.desktop`. With `ZENITH_PROFILE=name`, each profile has its own folder under `profiles/name/`.

## Uninstalling

Removing the app (deleting the AppImage, the `.app`, or using Windows "Apps & features") does **not** delete your data folder. That's on purpose: reinstalling or upgrading keeps your chats.
To remove everything, delete the data folder above as well. Models downloaded by Ollama live in Ollama's own folder (`~/.ollama/models`) and are removed with `ollama rm <model>`.

Before uninstalling or upgrading, take a backup from Settings → Backup. The restore preview checks the backup before anything is replaced.

## What the passcode lock does and doesn't do

- It stops anyone who opens Zenith, on this computer or over your network, from seeing your chats until they enter the passcode.
- It does **not** encrypt anything. The database, attachments and settings on disk can be read by anyone with access to your user account's files. That person can also remove the lock by clearing `lock_pass_hash` in `config.json`.
- A recovery code is shown once, when you turn the lock on. Use it from "Forgot passcode?" on the lock screen.
- "Sign out other devices" makes every other browser or phone enter the passcode again.
- For protection at rest, use full-disk encryption (FileVault, BitLocker, LUKS).

## Reporting a bug

System health → Diagnostic bundle shows exactly what it contains before you download it. Error messages include an error ID, which matches a line in the bundle's log.
