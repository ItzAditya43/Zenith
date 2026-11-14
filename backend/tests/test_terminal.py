"""Workspace terminal: a real shell on a pty, over HTTP."""
from __future__ import annotations

import base64
import sys
import time

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX pty only")


@pytest.fixture
def conv(client, tmp_path):
    from app.db import storage

    c = storage.create_conversation("term")
    storage.set_conversation_workdir(c["id"], str(tmp_path))
    yield c["id"], tmp_path
    from app.services import terminal_service
    terminal_service.kill_all()


def _read_until(client, sid, needle, since=0, timeout=10.0):
    out = b""
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/terminal/{sid}/output", params={"since": since, "wait": 2})
        assert r.status_code == 200
        body = r.json()
        out += base64.b64decode(body["data"])
        since = body["next"]
        if needle in out:
            return out, since, body
    raise AssertionError(f"{needle!r} not seen in {out[-500:]!r}")


def test_shell_runs_in_the_workdir_and_round_trips_input(client, conv):
    cid, workdir = conv
    (workdir / "marker.txt").write_text("x")
    r = client.post(f"/api/conversations/{cid}/terminal", json={"cols": 80, "rows": 24})
    assert r.status_code == 200
    sid = r.json()["session_id"]
    assert r.json()["cwd"] == str(workdir.resolve())

    assert client.post(f"/api/terminal/{sid}/input", json={"data": "ls; echo DONE-$((40+2))\n"}).status_code == 200
    out, since, _ = _read_until(client, sid, b"DONE-42")
    assert b"marker.txt" in out

    assert client.post(f"/api/terminal/{sid}/resize", json={"cols": 120, "rows": 40}).status_code == 200
    client.post(f"/api/terminal/{sid}/input", json={"data": "stty size\n"})
    _read_until(client, sid, b"40 120", since)


def test_reattaching_returns_the_same_session(client, conv):
    cid, _ = conv
    a = client.post(f"/api/conversations/{cid}/terminal", json={}).json()["session_id"]
    b = client.post(f"/api/conversations/{cid}/terminal", json={}).json()["session_id"]
    assert a == b


def test_exit_and_close(client, conv):
    cid, _ = conv
    sid = client.post(f"/api/conversations/{cid}/terminal", json={}).json()["session_id"]
    client.post(f"/api/terminal/{sid}/input", json={"data": "exit 3\n"})
    deadline = time.time() + 10
    body = {}
    while time.time() < deadline:
        body = client.get(f"/api/terminal/{sid}/output", params={"since": 0, "wait": 1}).json()
        if not body["alive"]:
            break
    assert body["alive"] is False and body["exit_code"] == 3
    assert client.post(f"/api/terminal/{sid}/input", json={"data": "ls\n"}).status_code == 409
    assert client.delete(f"/api/terminal/{sid}").json() == {"closed": True}
    assert client.get(f"/api/terminal/{sid}/output").status_code == 404


def test_foreign_origin_is_refused(client, conv):
    cid, _ = conv
    r = client.post(f"/api/conversations/{cid}/terminal", json={}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_text_plain_cross_site_post_is_rejected(client, conv):
    # A web page can send a "simple" cross-origin POST without a preflight;
    # FastAPI must refuse to parse a non-JSON body as the input model.
    cid, _ = conv
    sid = client.post(f"/api/conversations/{cid}/terminal", json={}).json()["session_id"]
    r = client.post(f"/api/terminal/{sid}/input", content='{"data": "touch pwned\\n"}',
                    headers={"Content-Type": "text/plain"})
    assert r.status_code == 422


def test_remote_clients_are_refused_by_default(client, conv, monkeypatch):
    from app.api import terminal as api

    monkeypatch.setattr(api, "is_local_client", lambda host: False)
    cid, _ = conv
    assert client.post(f"/api/conversations/{cid}/terminal", json={}).status_code == 403


def test_no_workdir_is_404(client):
    from app.db import storage

    c = storage.create_conversation("none")
    assert client.post(f"/api/conversations/{c['id']}/terminal", json={}).status_code == 404
