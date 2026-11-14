"""Browse the Ollama model library from inside Zenith.

Ollama has no public JSON API for its library, so this reads the same
pages a browser does (ollama.com/search and ollama.com/library/<name>) and
pulls out name, description, capabilities, sizes and download counts. If
the page layout changes, parsing returns fewer fields or nothing; it never
raises into the UI. Results are cached for a while to stay polite.

Only these two read-only pages are fetched, and only when you open the
library in Settings; nothing about you or your machine is sent.
"""
from __future__ import annotations

import html
import re
import time

import httpx

BASE = "https://ollama.com"
CACHE_SECONDS = 30 * 60
_cache: dict[str, tuple[float, object]] = {}

_CAPABILITIES = {"tools", "vision", "thinking", "embedding", "cloud", "audio"}
_SIZE = re.compile(r"^\d+(\.\d+)?[bmk]$|^e\d+b$|^\d+x\d+(\.\d+)?b$", re.I)


class LibraryError(RuntimeError):
    pass


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def parse_search(page: str) -> list[dict]:
    h = _squash(page)
    out = []
    seen = set()
    for chunk in re.split(r'<a href="/library/', h)[1:]:
        body = chunk.split("</li>")[0]
        name = body.split('"', 1)[0]
        if not name or ":" in name or "/" in name or name in seen:
            continue
        seen.add(name)
        chips = [html.unescape(c).strip() for c in re.findall(r'rounded-md [^"]*" ?>([^<]+)<', body)]
        caps = [c for c in chips if c.lower() in _CAPABILITIES]
        sizes = [c.lower() for c in chips if _SIZE.match(c)]
        desc = re.findall(r'<p class="mt-1[^"]*" ?>([^<]+)</p>', body)
        pulls = re.findall(r'title="([\d,]+) downloads"', body)
        updated = re.findall(r'title="Updated ([^"]+)"', body)
        out.append({
            "name": name,
            "description": html.unescape(desc[0]).strip() if desc else "",
            "capabilities": caps,
            "sizes": sizes,
            "cloud": "cloud" in [c.lower() for c in caps],
            "pulls": int(pulls[0].replace(",", "")) if pulls else None,
            "updated": updated[0] if updated else None,
        })
    return out


def _gb(text: str) -> float | None:
    m = re.match(r"([\d.]+)\s*(GB|MB|KB|TB)", text.strip(), re.I)
    if not m:
        return None
    n = float(m.group(1))
    return {"TB": n * 1024, "GB": n, "MB": n / 1024, "KB": n / 1024 / 1024}[m.group(2).upper()]


def parse_model_page(page: str, name: str) -> list[dict]:
    """Tags of one model with their download size, from its library page."""
    h = _squash(page)
    tags = []
    pattern = (
        r'<a href="/library/(' + re.escape(name) + r':[^"]+)" class="sm:hidden[^"]*"> <span[^>]*> '
        r'<p[^>]*>[^<]+</p> </span> <p class="flex text-neutral-500">([^<]+)</p>'
    )
    for tag, info in re.findall(pattern, h):
        fields = [f.strip() for f in html.unescape(info).split("·")]
        size_text = fields[0] if fields else ""
        sizes = [g for g in (_gb(p) for p in size_text.split(" - ")) if g is not None]
        context = next((f.replace(" context window", "") for f in fields if "context window" in f), None)
        tags.append({
            "tag": tag,
            "size": size_text if sizes else None,
            "size_gb": max(sizes) if sizes else None,
            "context": context,
            "cloud": tag.endswith("cloud"),
        })
    return tags


async def _get(path: str, params: dict | None = None) -> str:
    key = path + "?" + "&".join(f"{k}={v}" for k, v in sorted((params or {}).items()))
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]  # type: ignore[return-value]
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers={"User-Agent": "Zenith"}) as client:
            r = await client.get(BASE + path, params=params)
    except httpx.HTTPError as exc:
        raise LibraryError("Couldn't reach ollama.com. Check your internet connection.") from exc
    if r.status_code == 404:
        raise LibraryError("That model isn't in the Ollama library.")
    if r.status_code != 200:
        raise LibraryError(f"ollama.com answered {r.status_code}.")
    _cache[key] = (time.time(), r.text)
    return r.text


async def search(query: str = "", category: str = "") -> list[dict]:
    params = {}
    if query.strip():
        params["q"] = query.strip()[:100]
    if category in ("cloud", "embedding", "vision", "tools", "thinking"):
        params["c"] = category
    return parse_search(await _get("/search", params))


async def tags(name: str) -> list[dict]:
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,80}", name or ""):
        raise LibraryError("Invalid model name.")
    return parse_model_page(await _get(f"/library/{name}"), name)
