"""Settings history: log_change/list_history/revert_to, and that
config.settings.set() logs automatically."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

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
    from app.db.storage import init_db

    init_db()
    yield Path(d)
    cfg.refresh_paths()
    cfg.settings.reload()


def test_log_change_and_list_history(temp_data_dir):
    from app.services import settings_history_service as shs

    shs.log_change("some_key", "old", "new")
    shs.log_change("other_key", {"a": 1}, {"a": 2})

    all_history = shs.list_history()
    assert len(all_history) == 2
    # most recent first
    assert all_history[0]["key"] == "other_key"
    assert all_history[0]["old_value"] == {"a": 1}
    assert all_history[0]["new_value"] == {"a": 2}

    filtered = shs.list_history(key="some_key")
    assert len(filtered) == 1
    assert filtered[0]["key"] == "some_key"
    assert filtered[0]["old_value"] == "old"
    assert filtered[0]["new_value"] == "new"


def test_log_change_never_raises(temp_data_dir, monkeypatch):
    from app.services import settings_history_service as shs

    def boom(*a, **kw):
        raise RuntimeError("db exploded")

    monkeypatch.setattr(shs, "_conn", boom)
    shs.log_change("k", 1, 2)  # must not raise


def test_config_set_logs_history(temp_data_dir):
    from app.core.config import settings
    from app.services import settings_history_service as shs

    settings.set("digest_enabled", True)
    history = shs.list_history(key="digest_enabled")
    assert len(history) == 1
    assert history[0]["old_value"] is False
    assert history[0]["new_value"] is True


def test_config_set_noop_does_not_log(temp_data_dir):
    from app.core.config import settings
    from app.services import settings_history_service as shs

    settings.set("digest_enabled", False)  # same as default — no-op
    history = shs.list_history(key="digest_enabled")
    assert len(history) == 0


def test_revert_to(temp_data_dir):
    from app.core.config import settings
    from app.services import settings_history_service as shs

    settings.set("digest_enabled", True)
    history = shs.list_history(key="digest_enabled")
    assert len(history) == 1
    entry_id = history[0]["id"]

    result = shs.revert_to(entry_id)
    assert result == {"key": "digest_enabled", "reverted_to": False}
    assert settings.get("digest_enabled") is False

    # the revert itself is logged as a new entry — append-only, never erased
    history_after = shs.list_history(key="digest_enabled")
    assert len(history_after) == 2


def test_revert_to_unknown_id_raises(temp_data_dir):
    from app.services import settings_history_service as shs

    with pytest.raises(ValueError):
        shs.revert_to("not-a-real-id")
