"""Inline edit: one model call that rewrites a selected range, writes nothing."""
from __future__ import annotations

import pytest

SRC = "class Cart:\n    def total(self):\n        return sum(i['price'] for i in self.items)\n\n    def count(self):\n        return len(self.items)\n"


@pytest.fixture
def conv(client, fake_ollama, tmp_path):
    from app.db import storage

    (tmp_path / "cart.py").write_text(SRC)
    c = storage.create_conversation("inline")
    storage.set_conversation_workdir(c["id"], str(tmp_path))
    return c["id"], tmp_path, fake_ollama


def test_rewrites_only_the_selection_and_writes_nothing(client, conv):
    cid, root, fake = conv
    fake.queue("Here you go:\n```python\nreturn sum(i['price'] * i['qty'] for i in self.items)\n```")
    r = client.post(f"/api/conversations/{cid}/inline-edit", json={
        "path": "cart.py", "content": SRC, "from_line": 3, "to_line": 3, "instruction": "multiply by qty"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["original"] == "        return sum(i['price'] for i in self.items)"
    # The model dropped the indentation; it's restored.
    assert body["replacement"] == "        return sum(i['price'] * i['qty'] for i in self.items)"
    assert (root / "cart.py").read_text() == SRC
    prompt = fake.calls[-1]["messages"][0]["content"]
    assert "THE SELECTION (lines 3-3)" in prompt and "multiply by qty" in prompt and "def count" in prompt


def test_rejects_bad_ranges_and_paths(client, conv):
    cid, _, _ = conv
    bad = {"path": "cart.py", "content": SRC, "from_line": 5, "to_line": 99, "instruction": "x"}
    assert client.post(f"/api/conversations/{cid}/inline-edit", json=bad).status_code == 409
    esc = {"path": "../etc/passwd", "content": SRC, "from_line": 1, "to_line": 1, "instruction": "x"}
    assert client.post(f"/api/conversations/{cid}/inline-edit", json=esc).status_code == 400
