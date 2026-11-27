from __future__ import annotations


def test_todo_priority_project_search(client):
    client.post("/api/todos", json={"text": "low thing", "priority": 1, "project": "home"})
    t = client.post("/api/todos", json={"text": "urgent thing", "priority": 3, "project": "work"}).json()
    assert [x["text"] for x in client.get("/api/todos").json()][0] == "urgent thing"
    assert [x["text"] for x in client.get("/api/todos?project=home").json()] == ["low thing"]
    assert [x["text"] for x in client.get("/api/todos?q=URGENT").json()] == ["urgent thing"]
    assert client.get("/api/todos/projects").json() == ["home", "work"]
    assert client.patch(f"/api/todos/{t['id']}", json={"priority": 9}).status_code == 422
    client.patch(f"/api/todos/{t['id']}", json={"project": None})
    assert client.get("/api/todos/projects").json() == ["home"]


def test_note_history_restore_export(client):
    n = client.post("/api/notes", json={"content": "v1"}).json()
    client.patch(f"/api/notes/{n['id']}", json={"content": "v2"})
    hist = client.get(f"/api/notes/{n['id']}/history").json()
    assert [h["content"] for h in hist] == ["v1"]
    client.post(f"/api/notes/{n['id']}/restore", json={"version_id": hist[0]["id"]})
    assert client.get("/api/notes?q=v1").json()[0]["content"] == "v1"
    assert "v1" in client.get("/api/notes/export.md").text


def test_rule_dry_run_sends_nothing(client):
    r = client.post("/api/automation/rules/preview", json={
        "trigger_type": "urgent_email", "action_type": "todo", "action_config": {"text": "Reply to {from}"}}).json()
    assert r["text"] == "Reply to boss@example.com"
    assert client.get("/api/todos").json() == []
    r = client.post("/api/automation/rules/preview", json={
        "trigger_type": "urgent_email", "action_type": "webhook", "action_config": {"url": "http://169.254.169.254/x"}}).json()
    assert "problem" in r
