import time

from app.services import memory_service


def test_list_memories_since_filters_new(client):
    memory_service.add_memory("old fact about tea")
    cutoff = time.time()
    time.sleep(0.01)
    memory_service.add_memory("new fact about coffee")
    rows = client.get(f"/api/memories?since={cutoff}").json()
    assert [r["content"] for r in rows] == ["new fact about coffee"]
    assert len(client.get("/api/memories").json()) >= 2
