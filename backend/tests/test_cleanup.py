"""Knowledge cleanup: proposals, apply, undo."""
from __future__ import annotations

import time


def test_scan_apply_undo(fake_ollama, client, tmp_path):
    from app.db.storage import _conn
    from app.services import memory_service as ms
    from app.services import rag_service

    a = ms.add_memory("Prefers dark mode in every editor")
    b = ms.add_memory("Prefers dark mode in every code editor")
    old = ms.add_memory("Owns a red bicycle")
    long_ago = time.time() - 400 * 86400
    with _conn() as conn:
        conn.execute("UPDATE memories SET created_at = ? WHERE id = ?", (long_ago, old["id"]))
    gone = tmp_path / "gone.txt"
    rag_service.index_folder_file(str(gone), "notes about a file that was deleted " * 5, "f1")
    live = tmp_path / "live.txt"
    live.write_text("v1")
    rag_service.index_folder_file(str(live), "version one of the file " * 5, "f1")
    rag_service._conn().execute("UPDATE chunks SET created_at = 1000 WHERE source_id = ?", (str(live),))
    rag_service._conn().commit()

    props = {p["kind"]: p for p in client.get("/api/cleanup/scan").json()["proposals"]}
    assert set(props) >= {"duplicate_memory", "stale_memory", "orphan_source", "changed_file"}
    assert props["duplicate_memory"]["merged"] == "Prefers dark mode in every code editor"
    assert "never used" in props["stale_memory"]["detail"]

    pick = [props[k]["id"] for k in ("duplicate_memory", "stale_memory", "orphan_source")]
    res = client.post("/api/cleanup/apply", json={"ids": pick + ["nope"]}).json()
    assert len(res["applied"]) == 3 and res["skipped"] == 1
    active = [m["content"] for m in ms.list_memories() if m["enabled"]]
    assert active == ["Prefers dark mode in every code editor"]
    assert not any(s["source_id"] == str(gone) for s in rag_service.list_sources())

    assert client.post(f"/api/cleanup/undo/{res['batch_id']}").json()["restored"] >= 3
    contents = {m["content"]: m for m in ms.list_memories()}
    assert {"Prefers dark mode in every editor", "Owns a red bicycle"} <= set(contents)
    assert contents["Owns a red bicycle"]["enabled"] and a["id"] in {m["id"] for m in ms.list_memories()}
    assert "Prefers dark mode in every code editor" in contents and b["id"] in {m["id"] for m in ms.list_memories()}
    assert any(s["source_id"] == str(gone) for s in rag_service.list_sources())
    assert client.post(f"/api/cleanup/undo/{res['batch_id']}").status_code == 409


def test_near_duplicates_but_not_different_facts():
    from app.services.cleanup_service import DUP_THRESHOLD, _similar

    assert _similar("Runs a bakery called Crumb & Co", "Runs a bakery named Crumb & Co") >= DUP_THRESHOLD
    assert _similar("Uses fish shell", "Uses zsh shell") < DUP_THRESHOLD
    assert _similar("Lives in Berlin", "Works in Berlin office") < DUP_THRESHOLD
