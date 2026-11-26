"""Prompt templates with fields, and shareable packs with a preview."""
from __future__ import annotations

import pytest


def test_template_fields_and_fill():
    from app.services import packs_service as ps

    f = ps.template_fields("Review {{file}} for {{ focus | bugs }} as of {{date}}; again {{File}}")
    assert f == [{"name": "file", "default": None}, {"name": "focus", "default": "bugs"}]
    out = ps.fill_template("Review {{file}} for {{focus|bugs}} on {{date}}", {"file": "a.py"}, now=0)
    assert out.startswith("Review a.py for bugs on 19") and "{{" not in out
    for bad in ("Hi {{name", "Hi {{}}", "Hi {{1abc}}", "Hi name}}"):
        with pytest.raises(ValueError):
            ps.template_fields(bad)


def test_quick_action_api_validates_and_renders(client):
    assert client.post("/api/quick-actions", json={"name": "x", "prompt_template": "Fix {{thing"}).status_code == 422
    r = client.post("/api/quick-actions", json={"name": "Review", "prompt_template": "Review {{file}} for {{focus|bugs}}"}).json()
    assert [f["name"] for f in r["fields"]] == ["file", "focus"]
    assert client.get("/api/quick-actions").json()[0]["fields"][1]["default"] == "bugs"
    out = client.post("/api/quick-actions/render", json={"template": r["prompt_template"], "values": {"file": "main.py"}}).json()
    assert out["text"] == "Review main.py for bugs"


def test_pack_roundtrip_preview_and_import(client):
    from app.db import storage
    from app.services import persona_service

    client.post("/api/quick-actions", json={"name": "Summarise", "prompt_template": "Summarise {{text}}"})
    persona_service.create_persona("Terse", "Answer in one line.")
    storage.create_automation_rule("Ping", "digest_generated", {}, "webhook", {"url": "https://example.com/hook"})
    pack = client.get("/api/packs/export?name=Starter").json()
    assert pack["format"] == "zenith-pack" and len(pack["items"]["quick_actions"]) == 1

    # Same machine: everything is already there.
    prev = client.post("/api/packs/preview", json={"pack": pack}).json()
    assert prev["importable"] == 0 and all(i["duplicate"] for i in prev["items"])

    pack["items"]["quick_actions"].append({"name": "Broken", "prompt_template": "Oops {{x"})
    pack["items"]["personas"][0]["name"] = "Terse 2"
    pack["items"]["automation_rules"][0]["name"] = "Ping 2"
    prev = client.post("/api/packs/preview", json={"pack": pack}).json()
    by = {(i["kind"], i["name"]): i for i in prev["items"]}
    assert by[("quick_action", "Broken")]["problem"]
    assert "sends event data to https://example.com/hook" in by[("automation_rule", "Ping 2")]["permissions"]
    res = client.post("/api/packs/import", json={"pack": pack, "include": ["persona:0", "automation_rule:0"]}).json()
    assert res["added"] == {"quick_actions": 0, "personas": 1, "automation_rules": 1}
    rule = next(r for r in storage.list_automation_rules() if r["name"] == "Ping 2")
    assert rule["enabled"] in (0, False)  # imported rules start switched off
    assert client.post("/api/packs/preview", json={"pack": {"format": "nope"}}).status_code == 400
