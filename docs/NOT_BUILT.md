# Deliberately not built (and why)

A few capabilities on the roadmap were investigated and intentionally left out,
because building them well isn't possible in this project's current shape or
would do more harm than good. Documenting the reasoning so it isn't re-litigated
blindly later.

## True OS-level computer-use (screen capture + click/type of any desktop app)

**Not built.** Zenith already has real *browser* automation (headless Chromium
over CDP — see `browser_service.py`), which covers "drive a web UI." Full
desktop computer-use — controlling arbitrary native apps by screenshotting the
screen and synthesizing mouse/keyboard — was not built because:

- **The backend is headless.** It runs in a container (or, when packaged, as a
  background sidecar) with no display server attached. Screen capture / input
  synthesis need a live desktop session the backend can't see.
- **It's platform-specific and fragile.** It would require X11 + `xdotool`
  (Linux/X11 only — not Wayland), or the macOS Accessibility/CGEvent APIs, or
  the Windows UIAutomation/SendInput APIs — three separate implementations, each
  needing OS-level permissions the user must grant.
- **The security surface is severe.** A local model driving the real mouse and
  keyboard across every app (banking, email, password managers) is a
  qualitatively larger risk than the sandboxed browser or the approval-gated
  shell tools. It shouldn't be a casual default.

If pursued later, the right shape is a separate, explicitly-opted-in native
helper per OS that the packaged desktop app talks to — not something the
containerized backend does.

## Sandboxed agent execution (firejail / bubblewrap / gVisor)

**Investigated, shelved.** `bwrap`/`firejail` need nested unprivileged user
namespaces, which Docker's default seccomp profile blocks
(`clone`/`unshare` with `CLONE_NEWUSER` → "No permissions to create new
namespace"). Enabling them means running the backend container with
`--privileged` or `seccomp=unconfined`, which *weakens the container's own
isolation to add a nested one* — a bad tradeoff as a default. The container
boundary itself is already the sandbox for the common deployment; a real
in-container syscall sandbox would need a different runtime (e.g. gVisor as the
Docker runtime), which is an infrastructure choice for the operator, not
something Zenith can ship on by default.

## Auto-update

**Documented, not wired.** Tauri has a first-class updater, but it needs a real
release/hosting pipeline (a place to publish signed builds + an update
manifest). That's a distribution decision, not meaningful to stub in code. The
exact steps to enable it on top of the desktop scaffold are in `DESKTOP.md`.

## Multi-master sync

**Out of scope by design.** Multi-device *access* to one backend is built (see
`MULTIDEVICE.md`). Several independent instances syncing/merging offline edits
is a much larger project (CRDTs or a sync server) than anything else on the
roadmap and isn't planned.
