"""Web search + arbitrary-URL reading.

Two entry points the orchestrator uses:

  search(query)         -> DuckDuckGo HTML results (no API key, no cost —
                            keeps Zenith's "nothing leaves your machine
                            except your own tools" ethos as close as
                            possible for a feature that inherently needs
                            the open internet).
  fetch_url(url)         -> readable text for one URL. Special-cased for
                            GitHub (raw file / repo README) and Reddit
                            (its own read-only JSON API) since generic
                            HTML scraping does badly on both; everything
                            else goes through a generic <article>-first
                            HTML text extractor.

Both are blocking (httpx sync-free async client) and bounded — capped
result count, capped page size, capped extracted text — so one bad page
can't blow up the context window or hang a turn.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import quote_plus, urlparse

import httpx

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)


class WebError(RuntimeError):
    pass


def extract_urls(text: str, limit: int = 3) -> list[str]:
    """Pull out the first `limit` distinct URLs a user pasted into a
    message, so they get auto-fetched regardless of the search toggle —
    "read this link" shouldn't require an extra click."""
    seen: list[str] = []
    for m in URL_RE.finditer(text or ""):
        url = m.group(0).rstrip(".,;:!?")
        if url not in seen:
            seen.append(url)
        if len(seen) >= limit:
            break
    return seen


async def search(query: str, max_results: int | None = None) -> list[dict[str, str]]:
    """Web search, routed by `web_search_backend`:

      "duckduckgo" (default) -> html.duckduckgo.com/html/, the JS-free
        endpoint DDG serves to non-JS clients — no API key, but its CSS
        selectors are unofficial and can break if DDG redesigns the page.
      "searxng" -> your own self-hosted SearXNG instance's JSON API
        (`searxng_url`), a stable drop-in that avoids that fragility.

    Returns [{"title", "url", "snippet"}], best-effort empty list on any
    failure so a flaky network never fails the whole chat turn."""
    max_results = max_results or int(settings.get("web_search_max_results", 5))
    if settings.get("web_search_backend", "duckduckgo") == "searxng":
        return await _search_searxng(query, max_results)
    return await _search_duckduckgo(query, max_results)


async def _search_searxng(query: str, max_results: int) -> list[dict[str, str]]:
    base = (settings.get("searxng_url") or "").rstrip("/")
    if not base:
        log.warning("web.searxng_not_configured")
        return []
    timeout = float(settings.get("web_fetch_timeout_seconds", 8))
    try:
        async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": _UA}) as client:
            resp = await client.get(f"{base}/search", params={"q": query, "format": "json"})
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        log.warning("web.search_failed", query=query[:120], backend="searxng", error=str(exc))
        return []
    results = []
    for r in data.get("results", [])[:max_results]:
        results.append({
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "snippet": r.get("content", ""),
        })
    return results


async def _search_duckduckgo(query: str, max_results: int) -> list[dict[str, str]]:
    timeout = float(settings.get("web_fetch_timeout_seconds", 8))
    try:
        async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": _UA}) as client:
            resp = await client.get(
                "https://html.duckduckgo.com/html/", params={"q": query}
            )
            resp.raise_for_status()
    except Exception as exc:
        log.warning("web.search_failed", query=query[:120], error=str(exc))
        return []

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(resp.text, "lxml")
    results: list[dict[str, str]] = []
    for node in soup.select("div.result"):
        a = node.select_one("a.result__a")
        if not a or not a.get("href"):
            continue
        snippet_el = node.select_one("a.result__snippet") or node.select_one(".result__snippet")
        results.append({
            "title": a.get_text(strip=True),
            "url": _unwrap_ddg_redirect(a["href"]),
            "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
        })
        if len(results) >= max_results:
            break
    return results


def _unwrap_ddg_redirect(href: str) -> str:
    """DDG's HTML endpoint links go through /l/?uddg=<encoded target> —
    unwrap so we fetch the real page, not a redirect stub."""
    if href.startswith("//duckduckgo.com/l/") or "uddg=" in href:
        from urllib.parse import parse_qs, urlsplit, unquote
        qs = parse_qs(urlsplit(href if href.startswith("http") else "https:" + href).query)
        target = qs.get("uddg", [None])[0]
        if target:
            return unquote(target)
    return href


async def fetch_url(url: str) -> dict[str, Any] | None:
    """Fetch + extract readable text for one URL. Returns
    {"url", "title", "text"} or None on failure. Routes GitHub/Reddit
    through their APIs; everything else through generic HTML extraction."""
    max_chars = int(settings.get("web_fetch_max_chars", 4000))
    try:
        host = urlparse(url).netloc.lower()
        if host.endswith("github.com"):
            return await _fetch_github(url, max_chars)
        if host.endswith("reddit.com"):
            return await _fetch_reddit(url, max_chars)
        yt_id = _youtube_video_id(url)
        if yt_id:
            return await _fetch_youtube(url, yt_id, max_chars)
        return await _fetch_generic(url, max_chars)
    except Exception as exc:
        log.warning("web.fetch_failed", url=url[:200], error=str(exc))
        return None


async def _client(timeout: float | None = None) -> httpx.AsyncClient:
    timeout = timeout or float(settings.get("web_fetch_timeout_seconds", 8))
    return httpx.AsyncClient(timeout=timeout, headers={"User-Agent": _UA}, follow_redirects=True)


async def _fetch_generic(url: str, max_chars: int) -> dict[str, Any] | None:
    async with await _client() as client:
        resp = await client.get(url)
        resp.raise_for_status()
        ctype = resp.headers.get("content-type", "")
        if "text/html" not in ctype and "application/xhtml" not in ctype:
            # Plain text / markdown / etc. — use as-is, no HTML parsing needed.
            return {"url": url, "title": url, "text": resp.text[:max_chars]}

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(resp.text, "lxml")
    for tag in soup(["script", "style", "nav", "header", "footer", "noscript", "svg"]):
        tag.decompose()
    title = soup.title.get_text(strip=True) if soup.title else url
    main = soup.find("article") or soup.find("main") or soup.body or soup
    text = re.sub(r"\n{3,}", "\n\n", main.get_text("\n", strip=True))
    return {"url": url, "title": title, "text": text[:max_chars]}


async def _fetch_github(url: str, max_chars: int) -> dict[str, Any] | None:
    """Handles a file blob (-> raw.githubusercontent.com) and a bare
    repo URL (-> README via the public REST API, unauthenticated —
    rate-limited but fine for occasional personal use)."""
    m = re.match(
        r"https?://github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+)", url
    )
    if m:
        owner, repo, ref, path = m.groups()
        raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}"
        async with await _client() as client:
            resp = await client.get(raw_url)
            resp.raise_for_status()
            return {"url": url, "title": f"{owner}/{repo}:{path}", "text": resp.text[:max_chars]}

    m = re.match(r"https?://github\.com/([^/]+)/([^/]+?)/?$", url)
    if m:
        owner, repo = m.groups()
        api_url = f"https://api.github.com/repos/{owner}/{repo}/readme"
        async with await _client() as client:
            resp = await client.get(api_url, headers={"Accept": "application/vnd.github.raw+json"})
            resp.raise_for_status()
            return {"url": url, "title": f"{owner}/{repo} README", "text": resp.text[:max_chars]}

    return await _fetch_generic(url, max_chars)


async def _fetch_reddit(url: str, max_chars: int) -> dict[str, Any] | None:
    """Reddit's read-only JSON API (append .json, no auth needed) gives
    clean post + top-comment text instead of the JS-heavy HTML page.
    Some hosting providers' IP ranges get a 403 from Reddit regardless of
    UA — falls back to generic HTML extraction rather than failing."""
    json_url = url.split("?")[0].rstrip("/") + ".json"
    try:
        async with await _client() as client:
            resp = await client.get(json_url)
            resp.raise_for_status()
            data = resp.json()

        post = data[0]["data"]["children"][0]["data"]
        title = post.get("title", url)
        parts = [post.get("selftext", "").strip()]
        comments = data[1]["data"]["children"] if len(data) > 1 else []
        for c in comments[:5]:
            body = c.get("data", {}).get("body")
            if body:
                parts.append(f"> {body.strip()}")
        text = "\n\n".join(p for p in parts if p)
        return {"url": url, "title": title, "text": text[:max_chars] or title}
    except Exception as exc:
        log.debug("web.reddit_json_failed", url=url[:200], error=str(exc))
        return await _fetch_generic(url, max_chars)


_YT_ID_RE = re.compile(
    r"(?:youtube(?:-nocookie)?\.com/(?:watch\?v=|embed/|shorts/|v/)|youtu\.be/)"
    r"([A-Za-z0-9_-]{11})"
)


def _youtube_video_id(url: str) -> str | None:
    host = urlparse(url).netloc.lower()
    if not (host.endswith("youtube.com") or host.endswith("youtu.be")
            or host.endswith("youtube-nocookie.com")):
        return None
    m = _YT_ID_RE.search(url)
    return m.group(1) if m else None


async def _fetch_youtube(url: str, video_id: str, max_chars: int) -> dict[str, Any] | None:
    """YouTube pages are almost entirely client-rendered, so scraping the
    HTML gets nothing useful — instead pull the title via the keyless
    oEmbed endpoint and the spoken content via the video's own
    captions/auto-captions (youtube_transcript_api, also keyless).
    Returns a title-only result (rather than None) if captions are off
    for this video, so the model at least knows what was asked about."""
    title = url
    try:
        async with await _client(timeout=6) as client:
            resp = await client.get(
                "https://www.youtube.com/oembed", params={"url": url, "format": "json"}
            )
            if resp.status_code == 200:
                title = resp.json().get("title", url)
    except Exception as exc:
        log.debug("web.youtube_oembed_failed", video_id=video_id, error=str(exc))

    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        # The library is sync/blocking (does its own HTTP under the hood);
        # run it off the event loop like the other sync SDK calls in this
        # app (rag_service's embedding calls follow the same pattern).
        snippets = await asyncio.to_thread(
            lambda: list(YouTubeTranscriptApi().fetch(video_id))
        )
        text = " ".join(s.text for s in snippets).strip()
        text = re.sub(r"\s+", " ", text)
        if text:
            return {"url": url, "title": title, "text": text[:max_chars]}
    except Exception as exc:
        log.info("web.youtube_transcript_unavailable", video_id=video_id, error=str(exc)[:200])

    return {"url": url, "title": title, "text": f"(No captions available for this video: {title})"}
