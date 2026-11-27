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
