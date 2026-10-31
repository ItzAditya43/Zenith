import asyncio

from app.db import storage
from app.services import orchestrator, persona_service


def test_project_persona_and_instructions_apply_to_new_chats(client):
    persona = persona_service.create_persona("Reviewer", "You review code tersely.")
    proj = client.post("/api/projects", json={"name": "Zen"}).json()
    r = client.patch(f"/api/projects/{proj['id']}", json={"persona_id": persona["id"], "instructions": "Use British spelling."})
    assert r.status_code == 200 and r.json()["instructions"] == "Use British spelling."

    conv = storage.create_conversation("x", proj["id"])
    system, _ = asyncio.run(orchestrator._build_system_context(conv["id"], "hello there"))
    assert "You review code tersely." in system
    assert "Use British spelling." in system

    # Other chats are untouched.
    plain = storage.create_conversation("y")
    system, _ = asyncio.run(orchestrator._build_system_context(plain["id"], "hello there"))
    assert "British" not in system


def test_update_project_validates(client):
    proj = client.post("/api/projects", json={"name": "P"}).json()
    assert client.patch(f"/api/projects/{proj['id']}", json={"persona_id": "nope"}).status_code == 404
    assert client.patch("/api/projects/missing", json={"name": "x"}).status_code == 404
    assert client.patch(f"/api/projects/{proj['id']}", json={"name": ""}).json()["name"] == "P"
