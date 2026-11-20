# Deliberately not built (and why)

A few capabilities on the roadmap were investigated and intentionally left out,
because building them well isn't possible in this project's current shape or
would do more harm than good. Documenting the reasoning so it isn't re-litigated
blindly later.

## True OS-level computer-use — now built (opt-in)

Originally left out for the security surface and per-OS work. Built in
2026-11 as **Desktop control** (`app/services/desktop_control.py`), with
the safeguards that made it acceptable: off by default, every action
approval-gated outside full-auto, input refused while a password manager
has focus, and a method ladder that avoids pixel guessing (compositor
commands, keyboard, accessibility tree, OCR targets, then vision). Linux
with Hyprland first; Windows (UI Automation) and macOS (Accessibility API)
would need their own backends. See [FEATURES.md](FEATURES.md#desktop-control).

## Sandboxed agent execution (bubblewrap) — built for native installs

bubblewrap can't run *inside* the Docker deployment: Docker's default
seccomp profile blocks the nested user namespaces it needs, and weakening
the container to allow them would trade away the outer boundary. That
deployment's container already is the sandbox.

On native and desktop installs bubblewrap works unprivileged, so it's now
a sandbox mode (`agent_sandbox: "bwrap"`, Settings → Agent tools): the
working folder read-write at /workspace, system folders read-only, a
private /tmp, nothing else of your home, and no network unless enabled.
Docker remains the option on other systems. See `app/services/sandbox.py`.

## Auto-update (install step) — now built

Releases exist and are signed, so the install step is wired: the desktop
app checks GitHub Releases quietly 20 seconds after start and from the
tray's "Check for Updates…". When there's a new version it shows the
notes and asks; on "Install and restart" it downloads the update,
verifies its signature against the public key in `tauri.conf.json`,
replaces the app and restarts. Nothing installs without that click.

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
