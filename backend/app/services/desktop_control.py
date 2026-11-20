"""Desktop control for the agent: act on your real desktop, not just files.

Off unless `desktop_control_enabled` is on. Every action that changes
something (open, focus, type, press keys, click) goes through the agent's
approval gate like a file write; only looking (listing windows, reading the
screen, finding things on it) runs without asking in semi-auto.

Methods, most reliable first, so small local models rarely have to guess:

1. Direct control, no screen involved: the compositor (`hyprctl`) opens,
   focuses and moves windows and switches workspaces; `xdg-open` opens
   files and URLs.
2. Keyboard: `wtype` types text and presses shortcuts (Wayland virtual
   keyboard), with `ydotool` as fallback.
3. Clicking by name: `find` returns numbered targets from the accessibility
   tree (AT-SPI: real buttons, fields, menu items with their names) and,
   for apps without one, from OCR of a screenshot (`tesseract` word boxes).
   The model picks a number; `click` presses that element through its
   accessibility action when it has one, else moves the pointer to the
   centre of its box (`hyprctl dispatch movecursor`) and clicks (`ydotool`).
4. Reading the screen: a screenshot (`grim`) described by the vision model.

Linux with Hyprland first. `status()` says what's available so the UI and
the model can tell which methods work on this machine.

Blocked: typing, keys and clicks while a password manager has focus.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass, field

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

# Window classes that must never receive synthetic input from the agent.
BLOCKED_CLASSES = re.compile(
    r"keepass|bitwarden|1password|enpass|lastpass|proton[- ]?pass|seahorse|kwallet|gnome-keyring|pinentry",
    re.I,
)
MAX_TARGETS = 40


class DesktopError(RuntimeError):
    pass


def enabled() -> bool:
    return bool(settings.get("desktop_control_enabled", False))


def _have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def status() -> dict:
    hypr = bool(os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")) and _have("hyprctl")
    atspi = _system_python() is not None
    return {
        "platform": sys.platform,
        "enabled": enabled(),
        "hyprland": hypr,
        "screenshot": _have("grim"),
        "keyboard": _have("wtype") or _have("ydotool"),
        "pointer": hypr and _have("ydotool"),
        "accessibility": atspi,
        "ocr": _have("tesseract"),
    }


async def _run(*argv: str, timeout: float = 15, stdin: bytes | None = None) -> tuple[int, str, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise DesktopError(f"`{argv[0]}` isn't installed.") from exc
    try:
        out, err = await asyncio.wait_for(proc.communicate(stdin), timeout=timeout)
    except TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise DesktopError(f"`{argv[0]}` took too long.") from exc
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


async def _hypr(*args: str) -> str:
    if not status()["hyprland"]:
        raise DesktopError("Window control needs Hyprland (hyprctl). Other desktops aren't supported yet.")
    code, out, err = await _run("hyprctl", *args)
    if code != 0:
        raise DesktopError((err or out).strip() or "hyprctl failed")
    return out


async def _hypr_json(what: str):
    return json.loads(await _hypr("-j", what) or "null")


# --- windows / apps / workspaces ----------------------------------------------------

async def windows() -> list[dict]:
    clients = await _hypr_json("clients") or []
    active = (await _hypr_json("activewindow") or {}).get("address")
    out = []
    for c in clients:
        if not c.get("mapped", True):
            continue
        out.append({
            "address": c.get("address"), "class": c.get("class", ""), "title": c.get("title", ""),
            "workspace": (c.get("workspace") or {}).get("name"), "focused": c.get("address") == active,
        })
    return out


def _match_window(wins: list[dict], query: str) -> dict:
    q = query.strip().lower()
    if not q:
        raise DesktopError("Say which window.")
    exact = [w for w in wins if w["class"].lower() == q]
    hits = exact or [w for w in wins if q in w["class"].lower() or q in w["title"].lower()]
    if not hits:
        raise DesktopError(f"No open window matches '{query}'. Use desktop_windows to see what's open.")
    return hits[0]


async def focus(query: str) -> str:
    w = _match_window(await windows(), query)
    await _hypr("dispatch", "focuswindow", f"address:{w['address']}")
    return f"Focused {w['class']} — {w['title'][:80]}"


async def _focused_class() -> str:
    try:
        return str((await _hypr_json("activewindow") or {}).get("class") or "")
    except DesktopError:
        return ""


async def _guard_input() -> None:
    cls = await _focused_class()
    if BLOCKED_CLASSES.search(cls):
        raise DesktopError(f"Refused: the focused window ({cls}) is a password manager.")


def _desktop_entries() -> list[tuple[str, str, str]]:
    """(name, exec, desktop_id) from installed .desktop files."""
    dirs = [os.path.expanduser("~/.local/share/applications"), "/usr/share/applications",
            "/var/lib/flatpak/exports/share/applications",
            os.path.expanduser("~/.local/share/flatpak/exports/share/applications")]
    out = []
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for f in os.listdir(d):
            if not f.endswith(".desktop"):
                continue
            name = exe = ""
            nodisplay = False
            try:
                with open(os.path.join(d, f), encoding="utf-8", errors="ignore") as fh:
                    section = ""
                    for line in fh:
                        line = line.strip()
                        if line.startswith("["):
                            section = line
                            continue
                        if section != "[Desktop Entry]":
                            continue
                        if line.startswith("Name=") and not name:
                            name = line[5:]
                        elif line.startswith("Exec=") and not exe:
                            exe = re.sub(r"\s*%[fFuUdDnNickvm]", "", line[5:]).strip()
                        elif line.lower() == "nodisplay=true":
                            nodisplay = True
            except OSError:
                continue
            if name and exe and not nodisplay:
                out.append((name, exe, f[:-8]))
    return out


async def open_thing(target: str) -> str:
    """Open an app by name, or a URL / file path with its default app."""
    t = target.strip()
    if not t:
        raise DesktopError("Say what to open.")
    if re.match(r"^(https?://|mailto:|file://)", t) or os.path.exists(os.path.expanduser(t)):
        code, _, err = await _run("xdg-open", os.path.expanduser(t) if not re.match(r"^\w+:", t) else t, timeout=10)
        if code != 0:
            raise DesktopError(err.strip() or "xdg-open failed")
        return f"Opened {t}"
    entries = _desktop_entries()
    q = t.lower()
    match = (next((e for e in entries if e[0].lower() == q or e[2].lower() == q), None)
             or next((e for e in entries if q in e[0].lower() or q in e[2].lower()), None))
    if not match:
        raise DesktopError(f"No installed app called '{target}'.")
    await _hypr("dispatch", "exec", match[1])
    return f"Started {match[0]}"


async def workspace(name: str) -> str:
    await _hypr("dispatch", "workspace", str(name).strip())
    return f"Switched to workspace {name}"


async def move_window(query: str, ws: str) -> str:
    w = _match_window(await windows(), query)
    await _hypr("dispatch", "movetoworkspacesilent", f"{ws},address:{w['address']}")
    return f"Moved {w['class']} to workspace {ws}"


# --- keyboard ------------------------------------------------------------------------

_MODS = {"ctrl": "ctrl", "control": "ctrl", "alt": "alt", "shift": "shift", "super": "logo", "win": "logo",
         "meta": "logo", "cmd": "logo"}
_KEYS = {"enter": "Return", "return": "Return", "esc": "Escape", "escape": "Escape", "tab": "Tab",
         "space": "space", "backspace": "BackSpace", "delete": "Delete", "up": "Up", "down": "Down",
         "left": "Left", "right": "Right", "home": "Home", "end": "End", "pageup": "Prior", "pagedown": "Next"}


async def type_text(text: str) -> str:
    if not text:
        raise DesktopError("Nothing to type.")
    await _guard_input()
    if _have("wtype"):
        code, _, err = await _run("wtype", "--", text, timeout=30)
    else:
        code, _, err = await _run("ydotool", "type", "--", text, timeout=30)
    if code != 0:
        raise DesktopError(err.strip() or "typing failed")
    return f"Typed {len(text)} characters"


async def press_keys(combo: str) -> str:
    """'ctrl+t', 'enter', 'super+2', 'ctrl+shift+p'."""
    parts = [p.strip().lower() for p in combo.replace(" ", "").split("+") if p.strip()]
    if not parts:
        raise DesktopError("Say which keys.")
    await _guard_input()
    mods = [_MODS[p] for p in parts[:-1] if p in _MODS]
    if len(mods) != len(parts) - 1:
        raise DesktopError(f"Unknown modifier in '{combo}'. Use ctrl, alt, shift or super.")
    key = _KEYS.get(parts[-1], parts[-1])
    if len(key) == 1 or key in _KEYS.values() or re.fullmatch(r"F\d{1,2}", key, re.I):
        argv = ["wtype"]
        for m in mods:
            argv += ["-M", m]
        argv += ["-k", key] if len(key) > 1 else ["-k", key]
        for m in reversed(mods):
            argv += ["-m", m]
        code, _, err = await _run(*argv)
        if code != 0:
            raise DesktopError(err.strip() or "key press failed")
        return f"Pressed {combo}"
    raise DesktopError(f"Unknown key '{parts[-1]}'.")


# --- screen ----------------------------------------------------------------------------

async def screenshot_png(focused_monitor_only: bool = True) -> bytes:
    if not _have("grim"):
        raise DesktopError("Screen reading needs `grim`.")
    argv = ["grim"]
    if focused_monitor_only and status()["hyprland"]:
        mons = await _hypr_json("monitors") or []
        mon = next((m for m in mons if m.get("focused")), None)
        if mon:
            argv += ["-o", mon["name"]]
    argv.append("-")
    # grim writes PNG bytes to stdout, so read them raw (not through _run).
    proc = await asyncio.create_subprocess_exec(*argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err_b = await asyncio.wait_for(proc.communicate(), timeout=10)
    if proc.returncode != 0 or not out:
        raise DesktopError(err_b.decode(errors="replace").strip() or "screenshot failed")
    return out


async def _focused_monitor_offset() -> tuple[int, int]:
    if not status()["hyprland"]:
        return 0, 0
    mons = await _hypr_json("monitors") or []
    mon = next((m for m in mons if m.get("focused")), None)
    return (int(mon["x"]), int(mon["y"])) if mon else (0, 0)


async def describe_screen(question: str = "") -> str:
    """Screenshot of the focused monitor, described by the vision model."""
    png = await screenshot_png()
    from app.services.ollama_client import OllamaClient
    from app.services.router import ModelRegistry, ModelRouter

    registry = ModelRegistry()
    installed = await registry.models()
    model = ModelRouter(registry=registry)._match_capability("vision", installed)  # noqa: SLF001
    if not model:
        raise DesktopError("No vision model installed. Pull one (e.g. qwen2.5vl) to let the agent see the screen.")
    q = question.strip() or "Describe what is on this screen: which app and window, the main content, and the buttons or fields a user could interact with."
    text = await OllamaClient().chat(model, [{"role": "user", "content": q}], images_b64=[base64.b64encode(png).decode()])
    return text.strip()[:4000] or "(the vision model returned nothing)"


# --- finding and clicking targets --------------------------------------------------------

@dataclass
class Target:
    n: int
    source: str          # "a11y" | "ocr"
    label: str
    role: str
    box: tuple[int, int, int, int] | None   # x, y, w, h in global compositor coords
    ref: object = field(default=None, repr=False)  # AT-SPI child-index path, if it has an action


_targets: dict[str, tuple[float, list[Target]]] = {}  # conversation_id -> (time, targets)


# The accessibility tree is read by a helper run with the system Python,
# which has PyGObject (gi). The desktop app's bundled backend doesn't, and an
# AT-SPI object can't cross processes anyway, so targets are remembered by
# their child-index path and re-resolved when clicked.
_ATSPI_HELPER = r"""
import json, sys
import gi
gi.require_version("Atspi", "2.0")
from gi.repository import Atspi
INTERACTIVE = {"push button","toggle button","check box","radio button","menu item","link","entry","text",
  "combo box","list item","page tab","tree item","button","menu","check menu item","radio menu item",
  "spin button","password text","table cell","icon"}
def active_frames():
    d = Atspi.get_desktop(0)
    for i in range(d.get_child_count()):
        app = d.get_child_at_index(i)
        for j in range(app.get_child_count()):
            fr = app.get_child_at_index(j)
            try:
                if fr.get_state_set().contains(Atspi.StateType.ACTIVE):
                    yield [i, j], fr
            except Exception:
                pass
def node_at(path):
    n = Atspi.get_desktop(0)
    for k in path:
        n = n.get_child_at_index(k)
    return n
mode = sys.argv[1]
if mode == "find":
    q, limit, out = sys.argv[2].lower(), int(sys.argv[3]), []
    def walk(node, path, depth):
        if len(out) >= limit or depth > 40 or node is None:
            return
        try:
            name = (node.get_name() or "").strip(); role = node.get_role_name() or ""
            st = node.get_state_set()
            vis = st.contains(Atspi.StateType.SHOWING) and st.contains(Atspi.StateType.VISIBLE)
        except Exception:
            return
        if vis and role in INTERACTIVE and (not q or q in name.lower()):
            box = None
            try:
                e = node.get_extents(Atspi.CoordType.SCREEN)
                if e.width > 0 and e.height > 0:
                    box = [e.x, e.y, e.width, e.height]
            except Exception:
                pass
            acts = 0
            try:
                acts = node.get_n_actions()
            except Exception:
                pass
            out.append({"label": name or role, "role": role, "path": path, "box": box, "actions": acts})
        try:
            n = node.get_child_count()
        except Exception:
            return
        for i in range(min(n, 400)):
            try:
                walk(node.get_child_at_index(i), path + [i], depth + 1)
            except Exception:
                pass
    for p, fr in active_frames():
        walk(fr, p, 0)
    print(json.dumps(out))
elif mode == "act":
    n = node_at(json.loads(sys.argv[2]))
    n.do_action(0)
    print("ok")
"""


def _system_python() -> str | None:
    for cand in ("/usr/bin/python3", shutil.which("python3")):
        if cand and os.path.exists(cand):
            return cand
    return None


async def _atspi_find(query: str, limit: int) -> list[dict]:
    py = _system_python()
    if not py:
        return []
    try:
        code, out, _ = await _run(py, "-c", _ATSPI_HELPER, "find", query, str(limit), timeout=20)
    except DesktopError:
        return []
    if code != 0:
        return []
    try:
        return json.loads(out or "[]")
    except json.JSONDecodeError:
        return []


async def _atspi_act(path: list[int]) -> bool:
    py = _system_python()
    if not py:
        return False
    try:
        code, out, _ = await _run(py, "-c", _ATSPI_HELPER, "act", json.dumps(path), timeout=10)
    except DesktopError:
        return False
    return code == 0 and out.strip() == "ok"


async def _ocr_find(query: str, limit: int) -> list[tuple[str, tuple[int, int, int, int]]]:
    if not _have("tesseract"):
        return []
    png = await screenshot_png()
    ox, oy = await _focused_monitor_offset()
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(png)
        path = f.name
    try:
        code, out, _ = await _run("tesseract", path, "stdout", "--psm", "11", "tsv", timeout=60)
    finally:
        os.unlink(path)
    if code != 0:
        return []
    words = []
    for line in out.splitlines()[1:]:
        cols = line.split("\t")
        if len(cols) < 12 or not cols[11].strip():
            continue
        try:
            conf = float(cols[10])
            x, y, w, h = (int(cols[i]) for i in (6, 7, 8, 9))
        except ValueError:
            continue
        if conf < 55:
            continue
        words.append((cols[11].strip(), (x + ox, y + oy, w, h), (cols[2], cols[3], cols[4])))
    q = query.lower().split()
    hits: list[tuple[str, tuple[int, int, int, int]]] = []
    if not q:
        return [(word, box) for word, box, _ in words[:limit]]
    # Match a phrase within one OCR line: join consecutive words of the line.
    lines: dict[tuple, list] = {}
    for word, box, key in words:
        lines.setdefault(key, []).append((word, box))
    for seq in lines.values():
        text = [word.lower() for word, _ in seq]
        for i in range(len(seq)):
            if all(i + k < len(seq) and q[k] in text[i + k] for k in range(len(q))):
                span = seq[i:i + len(q)]
                x0 = min(b[0] for _, b in span)
                y0 = min(b[1] for _, b in span)
                x1 = max(b[0] + b[2] for _, b in span)
                y1 = max(b[1] + b[3] for _, b in span)
                hits.append((" ".join(w for w, _ in span), (x0, y0, x1 - x0, y1 - y0)))
                if len(hits) >= limit:
                    return hits
    return hits


async def find(conversation_id: str, query: str) -> str:
    """Numbered things on screen matching `query` (empty = all buttons and fields)."""
    targets: list[Target] = []
    for el in await _atspi_find(query, MAX_TARGETS):
        box = tuple(el["box"]) if el.get("box") else None
        targets.append(Target(len(targets) + 1, "a11y", el["label"], el["role"], box,
                              el["path"] if el.get("actions") else None))
    if len(targets) < 3:
        for text, box in await _ocr_find(query, MAX_TARGETS - len(targets)):
            targets.append(Target(len(targets) + 1, "ocr", text, "text on screen", box))
    _targets[conversation_id] = (time.time(), targets)
    if not targets:
        return (f"Nothing matching '{query}' found on screen. Try different words, desktop_screen to look, "
                "or keyboard shortcuts instead.")
    lines = [f"[{t.n}] {t.role}: {t.label[:80]}" + (" (via screen text)" if t.source == "ocr" else "") for t in targets]
    return "Targets (use desktop_click with the number):\n" + "\n".join(lines)


async def click(conversation_id: str, n: int, double: bool = False) -> str:
    entry = _targets.get(conversation_id)
    if not entry or time.time() - entry[0] > 120:
        raise DesktopError("No current targets. Run desktop_find first (targets expire after 2 minutes).")
    t = next((x for x in entry[1] if x.n == int(n)), None)
    if t is None:
        raise DesktopError(f"There's no target [{n}].")
    await _guard_input()
    if t.source == "a11y" and t.ref is not None and not double:
        if await _atspi_act(t.ref):  # type: ignore[arg-type]
            return f"Activated {t.role} '{t.label[:60]}'"
    if not t.box:
        raise DesktopError(f"Target [{n}] has no position on screen to click.")
    if not status()["pointer"]:
        raise DesktopError("Clicking needs Hyprland and ydotool.")
    x, y, w, h = t.box
    cx, cy = x + w // 2, y + h // 2
    await _hypr("dispatch", "movecursor", f"{cx} {cy}")
    await asyncio.sleep(0.05)
    for _ in range(2 if double else 1):
        code, _, err = await _run("ydotool", "click", "0xC0")
        if code != 0:
            raise DesktopError(err.strip() or "click failed (is ydotoold running?)")
        await asyncio.sleep(0.08)
    return f"Clicked '{t.label[:60]}' at {cx},{cy}"
