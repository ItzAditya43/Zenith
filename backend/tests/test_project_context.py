"""Project code context: incremental indexing, cited retrieval, recent runs."""
from __future__ import annotations

import time


def test_blocks_cut_at_blank_lines():
    from app.services.project_context import blocks

    text = "\n".join([f"line {i}" if i % 10 else "" for i in range(1, 131)])
    bs = blocks(text, 60)
    assert bs[0][0] == 1 and bs[0][1] in (50, 60) and bs[-1][1] <= 130
    assert all(b[0] == a[1] + 1 for a, b in zip(bs, bs[1:], strict=False))


def test_index_retrieve_and_incremental(fake_ollama, tmp_path):
    from app.db import storage
    from app.services import project_context as pc

    (tmp_path / "billing.py").write_text("def compute_invoice_total(items):\n    return sum(i.price for i in items)\n")
    (tmp_path / "README.md").write_text("# Shop\nInvoices are emailed on the first of the month.\n")
    (tmp_path / "logo.png").write_bytes(b"\x89PNG")
    st = pc.index_project(str(tmp_path))
    assert st["status"] == "done" and st["changed"] == 2
    hits = pc.retrieve(str(tmp_path), "compute_invoice_total")
    assert hits and hits[0]["path"] == "billing.py" and hits[0]["start"] == 1 and "sum(" in hits[0]["text"]

    again = pc.index_project(str(tmp_path))
    assert again["changed"] == 0  # nothing changed
    time.sleep(0.01)
    (tmp_path / "billing.py").write_text("def compute_invoice_total(items, tax):\n    return sum(i.price for i in items) * tax\n")
    (tmp_path / "README.md").unlink()
    third = pc.index_project(str(tmp_path))
    assert third["changed"] == 1 and third["removed"] == 1
    assert pc.status(str(tmp_path))["indexed_files"] == 1

    c = storage.create_conversation("code")
    block, cites = pc.context_block(c["id"], str(tmp_path), "how is compute_invoice_total calculated?")
    assert "[billing.py:1-2]" in block and cites[0]["kind"] == "code" and cites[0]["path"] == "billing.py"
    assert pc.context_block(c["id"], None, "x") == ("", [])


async def test_coding_chat_gets_project_context(fake_ollama, tmp_path):
    from app.db import storage
    from app.services import project_context as pc
    from app.services.orchestrator import _build_system_context

    (tmp_path / "auth.py").write_text("def rotate_session_token(user):\n    return user.id + 1\n")
    pc.index_project(str(tmp_path))
    c = storage.create_conversation("code")
    storage.set_conversation_workdir(c["id"], str(tmp_path))
    system, cites = await _build_system_context(c["id"], "where is rotate_session_token defined?")
    assert "auth.py:1-2" in system and any(x["kind"] == "code" for x in cites)
