"""Real browser automation for agent mode: navigate/click/type/read a live,
JS-rendered page — what `fetch_url` (static HTML only, see web_service.py)
can't do.

Design choice: raw Chrome DevTools Protocol over a websocket, driving the
system `chromium` package directly, instead of Playwright/Selenium. Those
pull 300MB+ of their own bundled browser binaries and a large dependency
tree; CDP is the same protocol they use underneath, and a minimal client
for it is ~100 lines. This mirrors the exact approach used throughout this
project's own manual UI testing (headless chromium + `websockets` +
`Runtime.evaluate`), just productionized into an agent tool.

One browser session per conversation (module-level dict, same "single
backend process" assumption as the shell-session and approval-future
registries in agent_service.py) — `browser_navigate` starts one if none is
open yet; `browser_close` (or a backend restart) ends it.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import socket
import tempfile
import time
from typing import Any

import httpx
import websockets

from app.core.logging import get_logger

log = get_logger(__name__)

_MAX_BROWSER_SESSIONS = 3
_CHROMIUM_CANDIDATES = ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable")

_browser_sessions: dict[str, dict[str, Any]] = {}


class BrowserError(RuntimeError):
    pass


def _find_chromium() -> str:
    for name in _CHROMIUM_CANDIDATES:
        path = shutil.which(name)
        if path:
            return path
    raise BrowserError(
        "No chromium binary found. Install one of: " + ", ".join(_CHROMIUM_CANDIDATES)
    )


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _CDPClient:
    """Minimal CDP request/response client: send a method, wait for the
    response with the matching id. One in-flight request at a time (a
    lock, not a dispatch table) — sufficient here since browser tool calls
    are inherently sequential (one action per model turn), and it avoids
    needing a background reader task to demux events from responses."""

    def __init__(self, ws):
        self.ws = ws
        self._id = 0
        self._lock = asyncio.Lock()

    async def send(self, method: str, params: dict | None = None, timeout: float = 15) -> dict:
        async with self._lock:
            self._id += 1
            msg_id = self._id
            await self.ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise BrowserError(f"CDP call {method} timed out.")
                raw = await asyncio.wait_for(self.ws.recv(), timeout=remaining)
                msg = json.loads(raw)
                if msg.get("id") == msg_id:
                    if "error" in msg:
                        raise BrowserError(f"CDP error on {method}: {msg['error']}")
                    return msg.get("result", {})
                # Anything else is an unsolicited event (Page.loadEventFired
                # etc.) — not needed for this simple call/response model.


async def _launch_session(conversation_id: str) -> dict:
    live = sum(1 for s in _browser_sessions.values())
    if live >= _MAX_BROWSER_SESSIONS:
        raise BrowserError(
            f"{_MAX_BROWSER_SESSIONS} browser sessions are already open — close one with browser_close first."
        )
    binary = _find_chromium()
    port = _free_port()
    user_data_dir = tempfile.mkdtemp(prefix="cortex-browser-")

    proc = await asyncio.create_subprocess_exec(
        binary,
        "--headless=new", "--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage",
        f"--remote-debugging-port={port}", f"--user-data-dir={user_data_dir}",
        "about:blank",
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True,  # own process group — see close_session
    )

    ws_url = None
    async with httpx.AsyncClient() as client:
        for _ in range(40):  # up to ~10s for chromium to come up
            await asyncio.sleep(0.25)
            try:
                r = await client.get(f"http://127.0.0.1:{port}/json", timeout=1.0)
                targets = r.json()
                pages = [t for t in targets if t.get("type") == "page"]
                if pages:
                    ws_url = pages[0]["webSocketDebuggerUrl"]
                    break
            except Exception:
                continue
    if ws_url is None:
        try:
            import os
            import signal
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            proc.kill()
        _kill_by_user_data_dir(user_data_dir)
        shutil.rmtree(user_data_dir, ignore_errors=True)
        raise BrowserError("Chromium didn't come up in time.")

    ws = await websockets.connect(ws_url, max_size=20_000_000)
    cdp = _CDPClient(ws)
    await cdp.send("Page.enable")
    await cdp.send("Runtime.enable")

    session = {
        "conversation_id": conversation_id, "proc": proc, "port": port,
        "user_data_dir": user_data_dir, "ws": ws, "cdp": cdp,
        "url": "about:blank", "created_at": time.time(),
    }
    _browser_sessions[conversation_id] = session
    return session


async def _get_or_create_session(conversation_id: str) -> dict:
    session = _browser_sessions.get(conversation_id)
    if session is not None:
        return session
    return await _launch_session(conversation_id)


def _kill_by_user_data_dir(user_data_dir: str) -> None:
    """Chromium's crashpad handler (and sometimes the zygote) calls its own
    setsid(), detaching into a new session/process group independently of
    the browser process — so even os.killpg() on the launched process's
    group leaves them running (verified: it did, during development).
    Matching every /proc/*/cmdline that references this session's unique
    --user-data-dir path and killing each directly sidesteps process-group
    semantics entirely and reliably gets all of them."""
    import os
    import signal

    needle = user_data_dir.encode()
    try:
        pids = [p for p in os.listdir("/proc") if p.isdigit()]
    except OSError:
        return
    for pid in pids:
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                cmdline = f.read()
        except OSError:
            continue
        if needle in cmdline:
            try:
                os.kill(int(pid), signal.SIGKILL)
            except ProcessLookupError:
                pass


async def close_session(conversation_id: str) -> bool:
    session = _browser_sessions.pop(conversation_id, None)
    if session is None:
        return False
    try:
        await session["ws"].close()
    except Exception:
        pass
    try:
        import os
        import signal
        os.killpg(os.getpgid(session["proc"].pid), signal.SIGKILL)
    except ProcessLookupError:
        pass
    except Exception:
        pass
    _kill_by_user_data_dir(session["user_data_dir"])
    try:
        await asyncio.wait_for(session["proc"].wait(), timeout=5)
    except Exception:
        pass
    shutil.rmtree(session["user_data_dir"], ignore_errors=True)
    return True


def _js_string(s: str) -> str:
    """Safely embed a Python string as a JS string literal in an
    Runtime.evaluate expression."""
    return json.dumps(s)


async def navigate(conversation_id: str, url: str, max_chars: int) -> str:
    if not url.strip():
        raise BrowserError("No url given.")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    session = await _get_or_create_session(conversation_id)
    cdp: _CDPClient = session["cdp"]
    await cdp.send("Page.navigate", {"url": url})
    await asyncio.sleep(1.5)  # pragmatic load grace period, not a real load-event wait
    session["url"] = url

    result = await cdp.send("Runtime.evaluate", {
        "expression": "({title: document.title, text: document.body ? document.body.innerText : ''})",
        "returnByValue": True,
    })
    value = result.get("result", {}).get("value", {}) or {}
    title = value.get("title", "")
    text = (value.get("text", "") or "")[:max_chars]
    return f"Navigated to {url}\nTitle: {title}\n\n{text}"


async def click(conversation_id: str, selector: str) -> str:
    session = _browser_sessions.get(conversation_id)
    if session is None:
        raise BrowserError("No browser session open — call browser_navigate first.")
    cdp: _CDPClient = session["cdp"]
    expr = f"""
    (() => {{
      const el = document.querySelector({_js_string(selector)});
      if (!el) return 'NOT_FOUND';
      el.click();
      return 'OK';
    }})()
    """
    result = await cdp.send("Runtime.evaluate", {"expression": expr, "returnByValue": True})
    outcome = result.get("result", {}).get("value")
    if outcome == "NOT_FOUND":
        return f"Error: no element matched selector {selector!r}."
    await asyncio.sleep(0.6)
    title_res = await cdp.send("Runtime.evaluate", {"expression": "document.title", "returnByValue": True})
    title = title_res.get("result", {}).get("value", "")
    return f"Clicked {selector!r}. Page title is now: {title}"


async def type_text(conversation_id: str, selector: str, text: str, submit: bool) -> str:
    session = _browser_sessions.get(conversation_id)
    if session is None:
        raise BrowserError("No browser session open — call browser_navigate first.")
    cdp: _CDPClient = session["cdp"]
    # Plain `.value = x` doesn't notify JS frameworks that listen for real
    # input events (React etc.) — use the native property setter + a
    # dispatched InputEvent, the same trick this project's own CDP test
    # tooling has used all along for controlled inputs.
    expr = f"""
    (() => {{
      const el = document.querySelector({_js_string(selector)});
      if (!el) return 'NOT_FOUND';
      const proto = el.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
      if (setter) {{ setter.call(el, {_js_string(text)}); }} else {{ el.value = {_js_string(text)}; }}
      el.dispatchEvent(new Event('input', {{ bubbles: true }}));
      el.dispatchEvent(new Event('change', {{ bubbles: true }}));
      return 'OK';
    }})()
    """
    result = await cdp.send("Runtime.evaluate", {"expression": expr, "returnByValue": True})
    outcome = result.get("result", {}).get("value")
    if outcome == "NOT_FOUND":
        return f"Error: no element matched selector {selector!r}."
    if submit:
        submit_expr = f"""
        (() => {{
          const el = document.querySelector({_js_string(selector)});
          const form = el && el.closest('form');
          if (form) {{ form.requestSubmit ? form.requestSubmit() : form.submit(); return 'SUBMITTED'; }}
          return 'NO_FORM';
        }})()
        """
        sub_res = await cdp.send("Runtime.evaluate", {"expression": submit_expr, "returnByValue": True})
        await asyncio.sleep(1.0)
        return f"Typed into {selector!r} and submitted ({sub_res.get('result', {}).get('value')})."
    return f"Typed into {selector!r}."


async def get_text(conversation_id: str, selector: str | None, max_chars: int) -> str:
    session = _browser_sessions.get(conversation_id)
    if session is None:
        raise BrowserError("No browser session open — call browser_navigate first.")
    cdp: _CDPClient = session["cdp"]
    if selector:
        expr = f"""
        (() => {{
          const el = document.querySelector({_js_string(selector)});
          return el ? el.innerText : null;
        }})()
        """
    else:
        expr = "document.body ? document.body.innerText : ''"
    result = await cdp.send("Runtime.evaluate", {"expression": expr, "returnByValue": True})
    value = result.get("result", {}).get("value")
    if value is None:
        return f"Error: no element matched selector {selector!r}."
    return str(value)[:max_chars]


def list_sessions() -> str:
    if not _browser_sessions:
        return "No browser sessions open."
    lines = [f"{cid}: {s['url']}" for cid, s in _browser_sessions.items()]
    return "\n".join(lines)
