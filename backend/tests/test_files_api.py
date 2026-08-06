"""Workspace file browser/editor API — scoped strictly to the
conversation's bound working directory (see app/api/files.py)."""
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


def _make_conversation_with_workdir(client, workdir: str) -> str:
    from app.db import storage

    conv = storage.create_conversation()
    storage.set_conversation_workdir(conv["id"], workdir)
    return conv["id"]


def test_files_endpoints_require_bound_workdir(client):
    from app.db import storage

    conv = storage.create_conversation()
    r = client.get(f"/api/conversations/{conv['id']}/files")
    assert r.status_code == 404


def test_list_read_write_round_trip(client, tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.txt").write_text("hello")
    cid = _make_conversation_with_workdir(client, str(tmp_path))

    r = client.get(f"/api/conversations/{cid}/files")
    assert r.status_code == 200
    names = {e["name"] for e in r.json()["entries"]}
    assert "sub" in names

    r = client.get(f"/api/conversations/{cid}/files/content", params={"path": "sub/a.txt"})
    assert r.status_code == 200
    assert r.json()["content"] == "hello"

    r = client.put(
        f"/api/conversations/{cid}/files/content",
        params={"path": "sub/a.txt"},
        json={"content": "updated"},
    )
    assert r.status_code == 200
    assert (tmp_path / "sub" / "a.txt").read_text() == "updated"


def test_write_creates_new_file(client, tmp_path):
    cid = _make_conversation_with_workdir(client, str(tmp_path))
    r = client.put(
        f"/api/conversations/{cid}/files/content",
        params={"path": "new.py"},
        json={"content": "print(1)\n"},
    )
    assert r.status_code == 200
    assert (tmp_path / "new.py").read_text() == "print(1)\n"


def test_path_cannot_escape_workdir(client, tmp_path):
    cid = _make_conversation_with_workdir(client, str(tmp_path))
    r = client.get(f"/api/conversations/{cid}/files/content", params={"path": "../../etc/passwd"})
    assert r.status_code == 400
