from __future__ import annotations


def test_draft_plan_and_plan_in_prompt(fake_ollama, client):
    fake_ollama.queue("1. What is X?\n- Who uses X\n* Costs of X\n")
    r = client.post("/api/research/plan", json={"topic": "Should I use X?"})
    assert r.status_code == 200
    assert r.json()["steps"] == ["What is X?", "Who uses X", "Costs of X"]
    assert client.post("/api/research/plan", json={}).status_code == 422
