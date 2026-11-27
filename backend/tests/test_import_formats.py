"""More import formats (Open WebUI, OpenAI-style, Markdown), duplicate
skipping with source tags, and export options that round-trip."""
from __future__ import annotations

import io
import json


def _upload(client, name, content):
    return client.post("/api/import", files={"file": (name, io.BytesIO(content.encode()), "application/octet-stream")})


def test_openai_and_open_webui_imports_dedupe(client):
    openai = [{"role": "system", "content": "be nice"}, {"role": "user", "content": "hi there"},
              {"role": "assistant", "content": [{"type": "text", "text": "hello!"}]}]
    r = _upload(client, "chat.json", json.dumps(openai)).json()
    assert {k: r[k] for k in ("conversations", "messages", "skipped_duplicates")} == {"conversations": 1, "messages": 2, "skipped_duplicates": 0}
    assert r["batch_id"]
    assert _upload(client, "chat.json", json.dumps(openai)).json()["skipped_duplicates"] == 1

    owui = [{"chat": {"title": "Branchy", "history": {"currentId": "c", "messages": {
        "a": {"role": "user", "content": "q", "parentId": None},
        "b": {"role": "assistant", "content": "old answer", "parentId": "a"},
        "c": {"role": "assistant", "content": "new answer", "parentId": "a"}}}}}]
    _upload(client, "owui.json", json.dumps(owui))
    convs = {c["title"]: c for c in client.get("/api/conversations").json()}
    assert convs["Branchy"]["tags"] == ["imported", "open-webui"]
    msgs = client.get(f"/api/conversations/{convs['Branchy']['id']}/messages").json()
    assert [m["content"] for m in msgs] == ["q", "new answer"]  # the active branch only
    assert convs["hi there"]["tags"] == ["imported", "openai-format"]


def test_markdown_export_round_trips(client):
    from app.db import storage

    c = storage.create_conversation("Recipe ideas")
    u = storage.add_message(c["id"], "user", "Something with lemons?")
    storage.add_message(c["id"], "assistant", "Lemon drizzle cake.\n\nWith **two** layers.", model="llama3.2:3b", parent_id=u["id"])
    full = client.get(f"/api/export/conversation/{c['id']}").text
    assert "## Assistant (llama3.2:3b" in full and "_Created" in full
    bare = client.get(f"/api/export/conversation/{c['id']}?metadata=false").text
    assert "llama3.2" not in bare and "_Created" not in bare
    js = client.get(f"/api/export/conversation/{c['id']}?format=json&metadata=false").json()
    assert js == {"title": "Recipe ideas", "messages": [
        {"role": "user", "content": "Something with lemons?"},
        {"role": "assistant", "content": "Lemon drizzle cake.\n\nWith **two** layers."}]}

    r = _upload(client, "recipe.md", full).json()
    assert r["conversations"] == 1 and r["messages"] == 2
    imported = [x for x in client.get("/api/conversations").json() if "markdown" in x["tags"]][0]
    msgs = client.get(f"/api/conversations/{imported['id']}/messages").json()
    assert imported["title"] == "Recipe ideas"
    assert msgs[1]["content"] == "Lemon drizzle cake.\n\nWith **two** layers."
    assert _upload(client, "x.md", "just some notes").status_code == 400


def test_bold_label_markdown():
    from app.services.import_service import parse_markdown

    out = parse_markdown("**You:**\nhello\n\n**ChatGPT:**\nhi!\nsecond line\n", "chat")
    assert out[0]["messages"] == [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi!\nsecond line"}]
