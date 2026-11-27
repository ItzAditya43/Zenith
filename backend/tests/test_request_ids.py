"""Every response carries X-Request-ID; unhandled errors return an error_id
that matches the log line."""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_request_id_header_and_passthrough(client):
    r = client.get("/api/version")
    assert len(r.headers["x-request-id"]) == 12
    r = client.get("/api/version", headers={"X-Request-ID": "my-trace-123"})
    assert r.headers["x-request-id"] == "my-trace-123"
    r = client.get("/api/version", headers={"X-Request-ID": "bad id with spaces"})
    assert r.headers["x-request-id"] != "bad id with spaces"


def test_unhandled_error_gets_error_id(temp_data_dir):
    import logging

    from app.main import app

    records: list[logging.LogRecord] = []

    class Grab(logging.Handler):
        def emit(self, record):
            records.append(record)

    h = Grab()
    logging.getLogger("zenith").addHandler(h)

    @app.get("/api/__boom_for_test")
    async def boom():
        raise RuntimeError("kaboom")

    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            r = c.get("/api/__boom_for_test")
        assert r.status_code == 500
        body = r.json()
        assert body["error_id"] and "kaboom" not in body["detail"]
        assert any(getattr(rec, "request_id", None) == body["error_id"] for rec in records)
    finally:
        logging.getLogger("zenith").removeHandler(h)
        app.router.routes[:] = [rt for rt in app.router.routes if getattr(rt, "path", "") != "/api/__boom_for_test"]


def test_logger_exception_works():
    from app.core.logging import get_logger
    try:
        raise ValueError("x")
    except ValueError:
        get_logger("t").exception("t.failed", thing=1)
