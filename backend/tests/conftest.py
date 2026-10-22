"""Shared fixtures. Test modules that define their own `temp_data_dir` /
`client` fixtures override these (pytest's nearest-definition rule)."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Starlette's TestClient reports its peer as "testclient" and sends
# Host: testserver — neither is a loopback IP or localhost, so without
# these NetworkGuard (app/core/security.py) would treat every test request
# as a remote client. Security tests opt into real remote/host values.
os.environ.setdefault("ZENITH_TRUSTED_NETWORKS", "testclient")
os.environ.setdefault("ZENITH_ALLOWED_HOSTS", "testserver")
os.environ.pop("ZENITH_HOST_BIND", None)


@pytest.fixture
def temp_data_dir(monkeypatch):
    d = tempfile.mkdtemp(prefix="zenith-test-")
    monkeypatch.delenv("CORTEX_DATA_DIR", raising=False)
    monkeypatch.setenv("ZENITH_DATA_DIR", d)
    from app.core import config as cfg

    cfg.refresh_paths()
    cfg.settings.reload()
    yield Path(d)
    cfg.refresh_paths()
    cfg.settings.reload()


@pytest.fixture
def client(temp_data_dir):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def fake_ollama(temp_data_dir, monkeypatch):
    """Scripted Ollama (see tests/fakes.py) on a fresh, migrated database."""
    from app.db.storage import init_db
    from app.services import rag_service
    from tests.fakes import FakeOllama

    rag_service.reset_conn()
    init_db()
    fake = FakeOllama().install(monkeypatch)
    yield fake
    rag_service.reset_conn()


async def collect(agen) -> list[dict]:
    """Drain an async generator of events into a list."""
    return [ev async for ev in agen]
