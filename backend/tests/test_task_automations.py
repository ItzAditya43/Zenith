"""Task-linked automations: rules that add to-dos, to-do events as
triggers, and schedules that turn their results into to-dos."""
from __future__ import annotations


async def test_rule_adds_todo_once_and_todo_events_fire(fake_ollama, client, monkeypatch):
    from app.db import storage
    from app.services import events

    r = client.post("/api/automation/rules", json={"name": "Reply", "trigger_type": "urgent_email",
                    "action_type": "todo", "action_config": {"text": "Reply to {from}: {subject}", "due_in_hours": 4}})
    assert r.status_code == 200
    assert client.post("/api/automation/rules", json={"name": "x", "trigger_type": "urgent_email",
                       "action_type": "todo", "action_config": {}}).status_code == 422
    seen = []
    client.post("/api/automation/rules", json={"name": "Hook", "trigger_type": "todo_created", "action_type": "webhook",
                "action_config": {"url": "https://example.com/h"}})
    from app.services import automation_service

    async def fake_hook(rule, data):
        seen.append(data["text"])

    monkeypatch.setattr(automation_service, "_run_webhook_action", fake_hook)
    await events.emit("urgent_email", {"from": "Ana", "subject": "Invoice"})
    await events.emit("urgent_email", {"from": "Ana", "subject": "Invoice"})
    todos = storage.list_todos()
    assert [t["text"] for t in todos] == ["Reply to Ana: Invoice"] and todos[0]["due_ts"]
    assert seen == ["Reply to Ana: Invoice"]  # other rules react; duplicates aren't re-added

    done = []
    client.post("/api/automation/rules", json={"name": "Done", "trigger_type": "todo_completed", "action_type": "webhook",
                "action_config": {"url": "https://example.com/d"}})

    async def hook2(rule, data):
        (done if rule["name"] == "Done" else seen).append(data["text"])

    monkeypatch.setattr(automation_service, "_run_webhook_action", hook2)
    client.patch(f"/api/todos/{todos[0]['id']}", json={"done": True})
    client.patch(f"/api/todos/{todos[0]['id']}", json={"done": True})
    assert done == ["Reply to Ana: Invoice"]  # only the transition fires


async def test_schedule_checklist_creates_todos(fake_ollama):
    from app.db import storage
    from app.services import schedule_service as ss

    sch = ss.create_schedule("Weekly review", "Review my week", "chat", 60, todo_mode="checklist")
    assert sch["todo_mode"] == "checklist"
    fake_ollama.queue("Good week.\n\n- [ ] Book dentist\n- [ ] Pay rent\n")
    res = await ss.run_schedule(ss.get_schedule(sch["id"]))
    assert res["todos_added"] == ["Book dentist", "Pay rent"]
    assert "End your reply with any follow-up tasks" in fake_ollama.prompts()[-1]
    assert {t["text"] for t in storage.list_todos()} == {"Book dentist", "Pay rent"}
    assert ss.checklist_items("- [ ] none") == []


async def test_schedule_add_mode(fake_ollama):
    from app.db import storage
    from app.services import schedule_service as ss

    sch = ss.create_schedule("News", "Top story?", "chat", 60, todo_mode="add")
    fake_ollama.queue("## Big launch today\nDetails here.")
    await ss.run_schedule(ss.get_schedule(sch["id"]))
    assert [t["text"] for t in storage.list_todos()] == ["News: Big launch today"]
