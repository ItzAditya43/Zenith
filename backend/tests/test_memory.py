"""memory_service: storage, dedupe, eviction, project scoping, relevance-
ranked injection, LLM fact extraction and contradiction review."""
from __future__ import annotations

import pytest


@pytest.fixture
def mem(fake_ollama):
    from app.core.config import settings
    from app.services import memory_service

    settings.update({"memory_enabled": True, "rag_embedding_model": "nomic-embed-text",
                     "memory_recall_top_k": 3, "memory_max_items": 200})
    return memory_service, fake_ollama


def test_add_normalises_and_dedupes(mem):
    svc, _ = mem
    assert svc.add_memory("  Uses   Arch Linux. ")["content"] == "Uses Arch Linux"
    assert svc.add_memory("uses arch linux") is None
    assert svc.add_memory("") is None
    assert svc.add_memory("x" * 301) is None
    assert [m["content"] for m in svc.list_memories()] == ["Uses Arch Linux"]


def test_oldest_memory_is_evicted_at_the_cap(mem):
    from app.core.config import settings

    svc, _ = mem
    settings.update({"memory_max_items": 2})
    first = svc.add_memory("fact one")
    svc.add_memory("fact two")
    svc.add_memory("fact three")
    contents = {m["content"] for m in svc.list_memories()}
    assert contents == {"fact two", "fact three"}
    from app.services import rag_service

    assert all(h["source_id"] != first["id"] for h in rag_service.retrieve("fact one", source_kind="memory"))


def test_disabled_and_deleted_memories_are_not_injected(mem):
    svc, _ = mem
    keep = svc.add_memory("Drinks oat milk")
    hide = svc.add_memory("Plays the cello")
    gone = svc.add_memory("Has a pet iguana")
    svc.set_enabled(hide["id"], False)
    svc.delete_memory(gone["id"])
    block = svc.memory_block()
    assert keep["content"] in block
    assert "cello" not in block and "iguana" not in block


def test_project_memories_only_surface_in_that_project(mem):
    from app.db import storage

    svc, _ = mem
    project = storage.create_project("Thesis")
    svc.add_memory("Thesis deadline is June 3", project_id=project["id"])
    svc.add_memory("Prefers metric units")
    assert "Thesis deadline" in svc.memory_block(project_id=project["id"])
    assert "Thesis deadline" not in svc.memory_block(project_id=None)
    assert "metric units" in svc.memory_block(project_id=None)


def test_many_memories_are_ranked_by_relevance(mem):
    svc, _ = mem
    for fact in ["Allergic to peanuts", "Drives a blue Volvo", "Works as a nurse",
                 "Supports Arsenal football club", "Grows tomatoes on the balcony"]:
        svc.add_memory(fact)
    block = svc.memory_block(query="what football club do I support")
    assert "Arsenal" in block
    assert block.count("\n- ") == 3  # top_k, not everything


def test_memory_disabled_returns_nothing(mem):
    from app.core.config import settings

    svc, _ = mem
    svc.add_memory("Anything")
    settings.update({"memory_enabled": False})
    assert svc.memory_block() == ""


def test_clear_removes_rows_and_vectors(mem):
    from app.services import rag_service

    svc, _ = mem
    svc.add_memory("one fact")
    svc.add_memory("another fact")
    assert svc.clear_memories() == 2
    assert rag_service.status()["chunks"] == 0


# --- extraction --------------------------------------------------------------------


async def test_extraction_stores_facts_with_project_scope(mem):
    from app.db import storage

    svc, fake = mem
    project = storage.create_project("Garden")
    conv = storage.create_conversation("c", project_id=project["id"])
    fake.queue('Sure! ```json\n["Grows chillies", "Lives in Leeds"]\n``` hope that helps [1]')
    added = await svc.extract_from_text("I grow chillies in my garden here in Leeds", conv["id"])
    assert [m["content"] for m in added] == ["Grows chillies", "Lives in Leeds"]
    assert all(m["project_id"] == project["id"] for m in added)
    assert fake.calls[-1]["model"] == "llama3.2:3b"


async def test_extraction_skips_short_messages_and_tolerates_garbage(mem):
    svc, fake = mem
    assert await svc.extract_from_text("ok thanks") == []
    assert fake.calls == []
    fake.queue("I don't think there's anything to remember here.")
    assert await svc.extract_from_text("what's the weather like tomorrow in town?") == []


async def test_extraction_caps_at_five_facts(mem):
    svc, fake = mem
    fake.queue(str([f"fact number {i}" for i in range(9)]).replace("'", '"'))
    assert len(await svc.extract_from_text("a long message full of personal details")) == 5


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('["a", "b"]', ["a", "b"]),
        ('prose [not json] then ["real fact"]', ["real fact"]),
        ('["uses [zsh] shell"] and more [brackets]', ["uses [zsh] shell"]),
        ("[]", []),
        ("no array at all", []),
        ('["ok", 3, null, "  "]', ["ok"]),
    ],
)
def test_parse_facts(raw, expected):
    from app.services.memory_service import _parse_facts

    assert _parse_facts(raw) == expected


# --- contradiction review -------------------------------------------------------------


async def test_conflict_review_records_valid_pairs_only(mem):
    from app.db import storage

    svc, fake = mem
    a = svc.add_memory("Uses fish shell")
    b = svc.add_memory("Uses zsh as their shell")
    svc.add_memory("Likes hiking")
    mems = svc.list_memories(include_disabled=False)
    ia = next(i for i, m in enumerate(mems) if m["id"] == a["id"])
    ib = next(i for i, m in enumerate(mems) if m["id"] == b["id"])
    fake.queue(f'[{{"a": {ia}, "b": {ib}, "reason": "can\'t use [both] as default"}}, '
               f'{{"a": 0, "b": 0, "reason": "self"}}, {{"a": 0, "b": 99, "reason": "out of range"}}]')
    created = await svc.review_conflicts()
    assert len(created) == 1
    conflicts = storage.list_memory_conflicts()
    assert {conflicts[0]["memory_id_a"], conflicts[0]["memory_id_b"]} == {a["id"], b["id"]}


async def test_conflict_review_needs_two_memories(mem):
    svc, fake = mem
    svc.add_memory("only one")
    assert await svc.review_conflicts() == []
    assert fake.calls == []
