from __future__ import annotations


def test_prompt_hidden_by_default_and_usage_csv(client):
    from app.core.config import settings
    from app.db.storage import _conn
    from app.services import trace_service

    t = trace_service.start("c", "chat", "my secret plans")
    t.finish("error", "failed for me@example.com")
    with _conn() as conn:
        row = conn.execute("SELECT user_text, error FROM turn_traces WHERE id = ?", (t.id,)).fetchone()
    assert "secret" not in row["user_text"] and "me@example.com" not in row["error"]
    settings.update({"trace_store_prompts": True})
    t2 = trace_service.start("c", "chat", "visible now")
    assert t2.user_text == "visible now"
    settings.update({"trace_store_prompts": False})
    r = client.get("/api/usage/export.csv")
    assert r.status_code == 200 and r.text.startswith("time_utc,model")
