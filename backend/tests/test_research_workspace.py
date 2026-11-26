"""Research workspaces: notes, claims tied to sources, and update re-runs."""
from __future__ import annotations

import asyncio
import json


def _report():
    from app.db import storage

    c = storage.create_conversation("r")
    return storage.create_research_report(c["id"], "Is sourdough healthier?", "Sourdough has a lower GI [1]. It tastes better.",
                                          [{"url": "https://a.org/gi", "title": "GI study"}, {"url": "https://b.org/x", "title": "Blog"}])


def test_notes_and_claims(fake_ollama, client):
    r = _report()
    assert client.patch(f"/api/research/reports/{r['id']}", json={"notes": "check the 2024 meta-analysis"}).json()["notes"]
    fake_ollama.queue(json.dumps([{"claim": "Sourdough has a lower GI", "sources": [1, 9]},
                                  {"claim": "It tastes better", "sources": []}]))
    claims = client.post(f"/api/research/reports/{r['id']}/claims").json()["claims"]
    assert claims == [{"claim": "Sourdough has a lower GI", "sources": [1], "supported": True},
                      {"claim": "It tastes better", "sources": [], "supported": False}]
    calls = len(fake_ollama.calls)
    client.post(f"/api/research/reports/{r['id']}/claims")
    assert len(fake_ollama.calls) == calls  # cached
    got = client.get(f"/api/research/reports/{r['id']}").json()
    assert got["notes"] == "check the 2024 meta-analysis" and got["claims"][1]["supported"] is False


async def test_rerun_saves_a_new_version_with_source_diff(fake_ollama, monkeypatch):
    from app.services import research_service
    from app.services import research_workspace as rw

    r = _report()

    async def fake_research(cid, text, att, history_last_model=None):
        yield {"type": "sources", "sources": [{"url": "https://a.org/gi", "title": "GI study"}, {"url": "https://c.org/new", "title": "New trial"}]}
        yield {"type": "done", "full_text": "Updated: still lower GI [1], confirmed by a 2026 trial [2].", "model": "m", "role": "research", "reason": "", "parent_id": None}

    monkeypatch.setattr(research_service, "run_deep_research", fake_research)
    rw.start_rerun(r["id"])
    for _ in range(200):
        if rw.rerun_status(r["id"])["status"] != "running":
            break
        await asyncio.sleep(0.01)
    st = rw.rerun_status(r["id"])
    assert st["status"] == "done", st
    assert [s["url"] for s in st["diff"]["added"]] == ["https://c.org/new"]
    assert [s["url"] for s in st["diff"]["dropped"]] == ["https://b.org/x"]
    vs = rw.versions(r["id"])
    assert [v["id"] for v in vs] == [r["id"], st["new_id"]]
    assert rw.versions(st["new_id"]) == vs
