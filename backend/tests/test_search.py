"""Confirms the FTS5 migration is recorded and that the search
function (FTS5 or LIKE fallback) returns the right conversations."""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

# Make `backend/` importable when pytest is invoked from the repo root.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


@pytest.fixture
def temp_data_dir(monkeypatch):
    d = tempfile.mkdtemp(prefix="cortex-search-")
    monkeypatch.setenv("CORTEX_DATA_DIR", d)
    from app.core import config as cfg

    cfg.refresh_paths()
    cfg.settings.reload()
    yield Path(d)
    cfg.refresh_paths()
    cfg.settings.reload()


def _has_fts5() -> bool:
    import sqlite3 as _sq

    try:
        rows = _sq.connect(":memory:").execute("PRAGMA compile_options").fetchall()
        return any("FTS5" in r[0] for r in rows)
    except Exception:
        return False


def test_fts_index_migration_runs(temp_data_dir):
    from app.db import storage

    storage.init_db()
    with storage._connect() as conn:
        v = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
        assert v >= 3, f"expected schema_version >= 3, got {v}"
        if _has_fts5():
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='messages_fts'"
            ).fetchone()
            assert row is not None, "messages_fts table missing after migration"
        else:
            row = conn.execute(
                "SELECT value FROM schema_meta WHERE key='fts5_available'"
            ).fetchone()
            assert row is not None, "schema_meta.fts5_available not recorded"
            assert row[0] in {"0", "1"}


def test_search_finds_matching_message(temp_data_dir):
    from app.db import storage
    from app.db.storage import search_conversations

    storage.init_db()
    c = storage.create_conversation("search test")
    storage.add_message(c["id"], "user", "Tell me about gardening tomatoes.")
    storage.add_message(c["id"], "assistant", "Tomatoes like full sun and rich soil.")
    storage.add_message(c["id"], "user", "Now about a different topic: quantum physics")
    results = search_conversations("tomato")
    assert results, "Expected at least one match for 'tomato'"
    assert results[0]["conversation_id"] == c["id"]
    assert results[0]["hits"] >= 2