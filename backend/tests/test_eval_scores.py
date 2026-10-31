from app.services import eval_scores


def test_record_and_show_in_models(client, monkeypatch):
    eval_scores.record("qwen2.5-coder:7b", 4, 5)
    eval_scores.record("qwen2.5-coder:7b", 5, 5)
    assert eval_scores.load()["qwen2.5-coder:7b"]["passed"] == 5

    from app.services.ollama_client import OllamaClient

    async def fake_list(self):
        return [{"name": "qwen2.5-coder:7b"}, {"name": "llama3.2:3b"}]

    monkeypatch.setattr(OllamaClient, "list_models", fake_list)
    rows = {m["name"]: m for m in client.get("/api/models").json()}
    assert rows["qwen2.5-coder:7b"]["agent_eval"]["total"] == 5
    assert rows["llama3.2:3b"]["agent_eval"] is None
