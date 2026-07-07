"""
Backend smoke + storage migration tests.

These cover the Phase 0 Definition of Done:
  - the app boots
  - /api/health returns 200
  - the schema_version migration table is created and baseline recorded
  - re-running migrations is idempotent (no duplicate version rows)
  - storage CRUD round-trips a conversation + message
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Make `backend/` importable when pytest is invoked from the repo root.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


@pytest.fixture
def temp_data_dir(monkeypatch):
    d = tempfile.mkdtemp(prefix="cortex-test-")
    monkeypatch.setenv("CORTEX_DATA_DIR", d)
    # Force settings to re-read from the new dir.
    from app.core import config as cfg

    cfg.settings.reload()
    yield Path(d)
    cfg.settings.reload()


def test_app_boots_and_health(temp_data_dir):
    from app.main import app

    with TestClient(app) as client:
        r = client.get("/api/health")
        # Health may report degraded (no Ollama in test env) but must be 200.
        assert r.status_code == 200, r.text
        body = r.json()
        assert "status" in body
        assert body["status"] in {"ok", "degraded", "down"}


def test_migration_runner_creates_baseline(temp_data_dir):
    from app.db import storage
    from app.db.migrations import current_version

    storage.init_db()
    # init_db() applies every pending migration, so baseline (v1) and
    # the attachments table (v2) should both be recorded on a fresh DB.
    assert current_version(storage._connect()) >= 2


def test_migration_runner_is_idempotent(temp_data_dir):
    from app.db import storage
    from app.db.migrations import current_version, run_migrations

    storage.init_db()
    version_after_init = current_version(storage._connect())
    conn = storage._connect()
    # Running again on the same connection must apply nothing new.
    report2 = run_migrations(conn)
    assert report2.applied == []
    assert current_version(conn) == version_after_init


def test_conversation_and_message_round_trip(temp_data_dir):
    from app.db import storage

    storage.init_db()
    conv = storage.create_conversation()
    cid = conv["id"]
    assert isinstance(cid, str) and cid
    storage.add_message(cid, "user", "hello world")
    storage.add_message(cid, "assistant", "hi there", model="general")

    msgs = storage.get_messages(cid)
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[1]["model"] == "general"
    assert msgs[0]["content"] == "hello world"
