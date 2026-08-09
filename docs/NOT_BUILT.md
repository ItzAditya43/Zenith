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
roadmap and isn't planned. A shortcut version — periodic export/import, or a
naive "last write wins" merge — was explicitly considered and rejected: either
one risks silently overwriting or duplicating real conversations across
devices, which is worse than not having the feature at all. If pursued later,
it needs actual conflict resolution (vector clocks or CRDTs per row), not an
approximation.

## Multi-user / teams mode

**Investigated, rejected as a drop-in.** Every table in this schema
(conversations, memories, personas, `config.json` itself) assumes exactly one
global user — there's no `user_id` column anywhere, no auth-to-data mapping,
no per-user scoping in any query. Adding real multi-user isolation means:

- A new `users` table, and a `user_id` (or equivalent) foreign key added to
  every existing table that currently has none — conversations, messages,
  memories, personas, projects, schedules, automation rules, snippets,
  quick actions, watched folders, and more.
- Every query in `storage.py` (100+ functions) re-audited to filter by the
  requesting user instead of returning global state.
- A real auth layer (sessions or tokens per user) replacing the current
  single shared-secret/passcode model, which authenticates *the app*, not
  *a person*.
- A decision about what stays shared (the Ollama connection, installed
  models) vs. what's per-user (everything else).

There is no safe partial version of this. Scoping "just the sidebar" or "just
memories" to a user while every other table stays global would create the
appearance of isolation without the substance — data would leak across
"users" who aren't actually separated, which is worse than the current
explicit single-user posture. If this is ever built, it's a dedicated
migration project audited table-by-table, not a feature added alongside
everything else.

## UI-panel plugin system

**Not built — MCP already covers the tool half.** [MCP client support](../README.md#mcp-client-support)
already gives external processes a real, sandboxed way to add *tools* to the
agent loop without a Zenith code change. A separate plugin API for adding
*UI panels* (a third-party settings section, a custom sidebar view) is a
different, larger surface — it needs a stable extension-facing frontend API,
a way to sandbox arbitrary rendered UI from a plugin author you may not trust
as much as your own tool-approval-gated MCP servers, and a versioning story
for that API as the app's own components change underneath it. [Quick actions](../README.md#interface)
covers the common "I want my own reusable command" case without any of that —
a real UI-panel plugin system is worth designing deliberately if it's ever
needed, not backed into alongside a dozen other features.
