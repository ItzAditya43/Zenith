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


def test_extract_project_with_no_code_blocks_returns_422(client):
    r = client.post("/api/conversations", json={"title": "empty chat"})
    cid = r.json()["id"]
    r = client.post(f"/api/conversations/{cid}/extract-project")
    assert r.status_code == 422


def test_extract_project_writes_files_and_binds_workdir(client):
    from app.db import storage

    conv = storage.create_conversation("My Project Idea")
    storage.add_message(conv["id"], "user", "write a hello world script")
    storage.add_message(
        conv["id"], "assistant",
        "Here you go:\n\n```python\n# file: hello.py\nprint('hello')\n```\n\n"
        "And a shell wrapper:\n\n```bash\npython hello.py\n```\n",
    )

    r = client.post(f"/api/conversations/{conv['id']}/extract-project")
    assert r.status_code == 200
    body = r.json()
    assert "hello.py" in body["files"]
    assert len(body["files"]) == 2

    from pathlib import Path
    workdir = Path(body["workdir"])
    assert "print('hello')" in (workdir / "hello.py").read_text()

    conv_after = client.get("/api/conversations").json()
    match = next(c for c in conv_after if c["id"] == conv["id"])
    assert match["workdir"] == body["workdir"]


def test_extract_project_avoids_filename_collisions(client):
    from app.db import storage

    conv = storage.create_conversation("Collisions")
    storage.add_message(
        conv["id"], "assistant",
        "```python\nprint(1)\n```\n\n```python\nprint(2)\n```\n",
    )
    r = client.post(f"/api/conversations/{conv['id']}/extract-project")
    assert r.status_code == 200
    files = r.json()["files"]
    assert len(files) == len(set(files))  # no duplicate names
