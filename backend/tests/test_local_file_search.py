"""Ad-hoc local file search — a scoped, non-persistent alternative to a
full OS-wide search index (see app/api/files.py)."""
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


def test_search_local_files_requires_real_directory(client):
    r = client.get("/api/search/local-files", params={"path": "/no/such/dir", "q": "x"})
    assert r.status_code == 404


def test_search_local_files_matches_content_and_filename(client, tmp_path):
    (tmp_path / "notes.md").write_text("meeting notes: discuss quarterly roadmap")
    (tmp_path / "roadmap.txt").write_text("nothing interesting here")

    r = client.get("/api/search/local-files", params={"path": str(tmp_path), "q": "roadmap"})
    assert r.status_code == 200
    body = r.json()
    paths = {m["path"] for m in body["matches"]}
    assert str(tmp_path / "notes.md") in paths
    assert str(tmp_path / "roadmap.txt") in paths
    kinds = {m["path"]: m["match"] for m in body["matches"]}
    assert kinds[str(tmp_path / "notes.md")] == "content"
    assert kinds[str(tmp_path / "roadmap.txt")] == "filename"


def test_search_local_files_skips_noise_dirs(client, tmp_path):
    noise = tmp_path / "node_modules"
    noise.mkdir()
    (noise / "pkg.js").write_text("findme")
    (tmp_path / "real.txt").write_text("findme")

    r = client.get("/api/search/local-files", params={"path": str(tmp_path), "q": "findme"})
    assert r.status_code == 200
    paths = {m["path"] for m in r.json()["matches"]}
    assert str(tmp_path / "real.txt") in paths
    assert str(noise / "pkg.js") not in paths
