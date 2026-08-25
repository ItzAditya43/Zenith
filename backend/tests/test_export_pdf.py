"""Single-conversation PDF export (app/api/export.py)."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


@pytest.fixture
def temp_data_dir(monkeypatch):
    d = tempfile.mkdtemp(prefix="cortex-test-")
    monkeypatch.setenv("CORTEX_DATA_DIR", d)
    from app.core import config as cfg

    cfg.refresh_paths()
    cfg.settings.reload()
    yield Path(d)
    cfg.refresh_paths()
    cfg.settings.reload()


@pytest.fixture
def client(temp_data_dir):
    from app.main import app

    with TestClient(app) as c:
        yield c


def test_export_pdf_returns_valid_pdf(client):
    from app.db import storage

    r = client.post("/api/conversations", json={"title": "PDF Export Test"})
    cid = r.json()["id"]
    storage.add_message(cid, "user", "Hello, can you show me some code?")
    storage.add_message(
        cid,
        "assistant",
        "Sure thing:\n\n```python\ndef greet():\n    print('hi')\n```\n\nHope that helps!",
        model="test-model",
    )

    r = client.get(f"/api/export/{cid}/pdf")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert "attachment" in r.headers["content-disposition"]
    assert r.content.startswith(b"%PDF-")
    assert len(r.content) > 500


def test_export_pdf_empty_conversation(client):
    r = client.post("/api/conversations", json={"title": "Empty"})
    cid = r.json()["id"]

    r = client.get(f"/api/export/{cid}/pdf")
    assert r.status_code == 200
    assert r.content.startswith(b"%PDF-")


def test_export_pdf_nonexistent_conversation(client):
    r = client.get("/api/export/does-not-exist/pdf")
    assert r.status_code == 404
