"""Changes tab: structured git status, diffs, stage/unstage, commit, branches, push."""
from __future__ import annotations

import subprocess

import pytest


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repo(client, tmp_path):
    from app.db import storage

    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")
    (root / "a.py").write_text("x = 1\n")
    (root / "gone.txt").write_text("bye\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    c = storage.create_conversation("git")
    storage.set_conversation_workdir(c["id"], str(root))
    return c["id"], root


def test_status_splits_staged_and_unstaged(client, repo):
    cid, root = repo
    (root / "a.py").write_text("x = 2\n")
    (root / "new.py").write_text("y = 1\n")
    (root / "gone.txt").unlink()
    (root / "staged.py").write_text("z\n")
    _git(root, "add", "staged.py")
    st = client.get(f"/api/conversations/{cid}/git").json()
    assert st["is_repo"] and st["branch"] == "main" and st["upstream"] is None
    assert st["staged"] == [{"path": "staged.py", "status": "added"}]
    assert {(f["path"], f["status"]) for f in st["unstaged"]} == {
        ("a.py", "modified"), ("new.py", "untracked"), ("gone.txt", "deleted")}


def test_file_diff_for_tracked_and_untracked(client, repo):
    cid, root = repo
    (root / "a.py").write_text("x = 2\n")
    (root / "new.py").write_text("hello\n")
    d = client.get(f"/api/conversations/{cid}/git/file-diff", params={"path": "a.py"}).json()["diff"]
    assert "-x = 1" in d and "+x = 2" in d
    d = client.get(f"/api/conversations/{cid}/git/file-diff", params={"path": "new.py"}).json()["diff"]
    assert "+hello" in d


def test_stage_unstage_commit_and_log(client, repo):
    cid, root = repo
    (root / "a.py").write_text("x = 3\n")
    r = client.post(f"/api/conversations/{cid}/git/commit", json={"message": "nothing staged"})
    assert r.status_code == 409 and "Nothing is staged" in r.json()["detail"]
    st = client.post(f"/api/conversations/{cid}/git/stage", json={"paths": ["a.py"]}).json()
    assert st["staged"] == [{"path": "a.py", "status": "modified"}]
    st = client.post(f"/api/conversations/{cid}/git/unstage", json={"paths": ["a.py"]}).json()
    assert st["staged"] == [] and st["unstaged"][0]["path"] == "a.py"
    client.post(f"/api/conversations/{cid}/git/stage", json={"paths": ["a.py"]})
    r = client.post(f"/api/conversations/{cid}/git/commit",
                    json={"message": "Bump x\n\nCo-Authored-By: Bot <bot@example.com>"}).json()
    assert r["commit"].endswith("Bump x") and r["status"]["staged"] == []
    assert "Co-Authored-By" not in _git(root, "log", "-1", "--format=%B")
    commits = client.get(f"/api/conversations/{cid}/git/log").json()["commits"]
    assert [c["subject"] for c in commits] == ["Bump x", "init"]


def test_paths_outside_the_folder_and_option_injection_are_refused(client, repo):
    cid, _ = repo
    for bad in ("../etc/passwd", "--output=/tmp/x", "/etc/passwd"):
        r = client.post(f"/api/conversations/{cid}/git/stage", json={"paths": [bad]})
        assert r.status_code == 409, bad


def test_branches_create_and_switch(client, repo):
    cid, _ = repo
    st = client.post(f"/api/conversations/{cid}/git/switch", json={"name": "zenith/fix-1", "create": True}).json()
    assert st["branch"] == "zenith/fix-1"
    b = client.get(f"/api/conversations/{cid}/git/branches").json()
    assert b["current"] == "zenith/fix-1" and set(b["branches"]) == {"main", "zenith/fix-1"}
    assert client.post(f"/api/conversations/{cid}/git/switch", json={"name": "-x"}).status_code == 409
    assert client.post(f"/api/conversations/{cid}/git/switch", json={"name": "a..b"}).status_code == 409


def test_push_sets_upstream_to_a_local_remote(client, repo, tmp_path):
    cid, root = repo
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", str(remote))
    _git(root, "remote", "add", "origin", str(remote))
    r = client.post(f"/api/conversations/{cid}/git/push").json()
    assert r["status"]["upstream"] == "origin/main" and r["status"]["ahead"] == 0
    (root / "a.py").write_text("x = 9\n")
    _git(root, "commit", "-qam", "more")
    assert client.get(f"/api/conversations/{cid}/git").json()["ahead"] == 1


def test_not_a_repo(client, tmp_path):
    from app.db import storage

    c = storage.create_conversation("plain")
    storage.set_conversation_workdir(c["id"], str(tmp_path))
    assert client.get(f"/api/conversations/{c['id']}/git").json() == {"is_repo": False}


def test_github_without_gh(client, repo, monkeypatch):
    from app.services import git_workspace

    monkeypatch.setattr(git_workspace, "gh_installed", lambda: False)
    cid, _ = repo
    assert client.get(f"/api/conversations/{cid}/github").json() == {"installed": False, "logged_in": False}
    r = client.get(f"/api/conversations/{cid}/github/issues")
    assert r.status_code == 409 and "GitHub CLI" in r.json()["detail"]


def test_separate_copy_gets_its_own_branch_folder_and_chat(client, repo):
    from app.db import storage

    cid, root = repo
    r = client.post(f"/api/conversations/{cid}/git/worktrees", json={"name": "Try new pricing"})
    assert r.status_code == 200, r.text
    wt = r.json()
    assert wt["branch"] == "zenith/try-new-pricing"
    assert wt["path"].endswith("repo.zenith/try-new-pricing")
    assert storage.get_conversation_workdir(wt["conversation_id"]) == wt["path"]
    # Work in the copy doesn't touch the main checkout.
    from pathlib import Path
    (Path(wt["path"]) / "a.py").write_text("x = 100\n")
    assert (root / "a.py").read_text() == "x = 1\n"
    st = client.get(f"/api/conversations/{wt['conversation_id']}/git").json()
    assert st["branch"] == "zenith/try-new-pricing" and st["unstaged"][0]["path"] == "a.py"

    listed = client.get(f"/api/conversations/{cid}/git/worktrees").json()["worktrees"]
    assert [w["branch"] for w in listed] == ["zenith/try-new-pricing"]
    # Dirty copies aren't removed.
    r = client.post(f"/api/conversations/{cid}/git/worktrees/remove", json={"path": wt["path"]})
    assert r.status_code == 409 and "uncommitted" in r.json()["detail"]
    _git(wt["path"], "checkout", "--", "a.py")
    assert client.post(f"/api/conversations/{cid}/git/worktrees/remove", json={"path": wt["path"]}).status_code == 200
    # Only this repo's copies can be removed.
    r = client.post(f"/api/conversations/{cid}/git/worktrees/remove", json={"path": "/tmp"})
    assert r.status_code == 409
