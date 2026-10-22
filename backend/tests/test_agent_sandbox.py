"""Agent risk classification hardening + the optional docker sandbox
(app/services/sandbox.py)."""
from __future__ import annotations

import shutil
import subprocess

import pytest


@pytest.fixture
def workdir(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("print('hi')\n")
    return str(tmp_path)


# --- bash classification ----------------------------------------------------


@pytest.mark.parametrize(
    "cmd",
    [
        "ls",
        "ls -la src",
        "cat src/a.py",
        "grep -rn print .",
        "git status",
        "git log --oneline -5",
        "git diff HEAD~1",
        "find . -name '*.py'",
        "wc -l src/a.py",
        "hostname",
    ],
)
def test_read_only_commands_in_workdir_are_safe(cmd, workdir):
    from app.services.agent_service import _classify_bash_command

    assert _classify_bash_command(cmd, workdir) == "safe"


@pytest.mark.parametrize(
    "cmd",
    [
        "git reset --hard",
        "git clean -fdx",
        "git push --force",
        "git checkout -- .",
        "git -c core.pager=sh log",
        "git diff --output=/tmp/x",
        "git",
        "find . -delete",
        "find . -name x -exec rm {} +",
        "env",
        "env python evil.py",
        "ls\npython evil.py",
        "ls\rpython evil.py",
        "cat ~/.ssh/id_rsa",
        "cat /etc/passwd",
        "cat ../../outside.txt",
        "cat $HOME/.bashrc",
        "tree -o out.txt",
        "date -s '2020-01-01'",
        "hostname pwned",
        "ls 'unterminated",
        "python script.py",
        "",
    ],
)
def test_writers_executors_and_out_of_tree_reads_are_risky(cmd, workdir):
    from app.services.agent_service import _classify_bash_command

    assert _classify_bash_command(cmd, workdir) == "risky"


def test_absolute_path_inside_workdir_is_still_safe(workdir):
    from app.services.agent_service import _classify_bash_command

    assert _classify_bash_command(f"cat {workdir}/src/a.py", workdir) == "safe"


def test_file_reads_are_safe_only_inside_workdir(workdir):
    from app.services.agent_service import classify_risk

    assert classify_risk("read_file", {"path": "src/a.py"}, workdir) == "safe"
    assert classify_risk("list_dir", {"path": "."}, workdir) == "safe"
    assert classify_risk("read_file", {"path": "/etc/passwd"}, workdir) == "risky"
    assert classify_risk("read_file", {"path": "../escape"}, workdir) == "risky"
    assert classify_risk("read_file", {"path": "src/a.py"}, None) == "risky"


def test_symlink_escaping_workdir_is_risky(workdir, tmp_path_factory):
    import os

    from app.services.agent_service import classify_risk

    outside = tmp_path_factory.mktemp("outside")
    (outside / "secret").write_text("x")
    os.symlink(outside / "secret", os.path.join(workdir, "link"))
    assert classify_risk("read_file", {"path": "link"}, workdir) == "risky"


# --- sandbox: pure helpers ---------------------------------------------------


@pytest.fixture
def sandbox_on(temp_data_dir):
    from app.core.config import settings

    settings.update({"agent_sandbox": "docker"})
    yield settings
    settings.update({"agent_sandbox": "off"})


def test_sandbox_off_by_default(temp_data_dir):
    from app.services import sandbox

    assert sandbox.enabled() is False
    assert sandbox.status()["mode"] == "off"


def test_effective_workdir_gives_scratch_space_when_sandboxed(sandbox_on, temp_data_dir):
    from app.services.agent_service import effective_workdir

    wd = effective_workdir("conv-1", None)
    assert wd and wd.startswith(str(temp_data_dir.resolve()))
    assert effective_workdir("conv-1", "/some/dir") == "/some/dir"


def test_effective_workdir_untouched_when_sandbox_off(temp_data_dir):
    from app.services.agent_service import effective_workdir

    assert effective_workdir("conv-1", None) is None


def test_container_cwd_mapping(workdir):
    from pathlib import Path

    from app.services import sandbox

    root = Path(workdir).resolve()
    assert sandbox.container_cwd(None, root) == "/workspace"
    assert sandbox.container_cwd("src", root) == "/workspace/src"
    assert sandbox.container_cwd(str(root / "src"), root) == "/workspace/src"
    with pytest.raises(sandbox.SandboxError):
        sandbox.container_cwd("/etc", root)
    with pytest.raises(sandbox.SandboxError):
        sandbox.container_cwd("../..", root)


def test_build_argv_locks_container_down(sandbox_on, workdir, monkeypatch):
    from pathlib import Path

    from app.services import sandbox

    monkeypatch.setattr(sandbox, "docker_path", lambda: "/usr/bin/docker")
    argv = sandbox.build_argv("echo hi", Path(workdir), None, "zenith-sbx-test")
    joined = " ".join(argv)
    assert argv[:3] == ["/usr/bin/docker", "run", "--rm"]
    assert "--network none" in joined
    assert "--cap-drop ALL" in joined
    assert "--security-opt no-new-privileges" in joined
    assert f"{Path(workdir)}:/workspace" in joined
    assert argv[-3:] == ["sh", "-c", "echo hi"]


def test_build_argv_errors_clearly_without_docker(sandbox_on, workdir, monkeypatch):
    from pathlib import Path

    from app.services import sandbox

    monkeypatch.setattr(sandbox, "docker_path", lambda: None)
    with pytest.raises(sandbox.SandboxError, match="docker CLI"):
        sandbox.build_argv("echo hi", Path(workdir), None, "n")


def test_file_tools_confined_to_workspace_when_sandboxed(sandbox_on, workdir):
    from app.services.agent_service import _run_read_file, _run_write_file

    assert _run_read_file({"path": "src/a.py"}, 1000, workdir).startswith("print")
    assert "outside the sandbox" in _run_read_file({"path": "/etc/hostname"}, 1000, workdir)
    assert "outside the sandbox" in _run_write_file({"path": "../escape.txt", "content": "x"}, workdir)


def test_sandboxed_bash_routes_through_docker(sandbox_on, workdir, monkeypatch):
    import asyncio

    from app.services import agent_service, sandbox

    calls = []

    async def fake_run(command, root, cwd, timeout, merge_stderr=False):
        calls.append((command, str(root), cwd))
        return 0, "hello\n", ""

    monkeypatch.setattr(sandbox, "run", fake_run)
    out = asyncio.run(agent_service._run_bash({"command": "echo hello"}, 5, 1000, workdir))
    assert calls == [("echo hello", workdir, None)]
    assert "exit_code: 0" in out and "hello" in out


# --- sandbox: real docker ----------------------------------------------------


def _docker_ready() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        subprocess.run(["docker", "image", "inspect", "python:3.12-slim"], check=True, capture_output=True, timeout=10)
        return True
    except Exception:
        return False


@pytest.mark.integration
@pytest.mark.skipif(not _docker_ready(), reason="needs docker + python:3.12-slim image")
def test_real_container_sees_only_workspace_and_no_network(sandbox_on, workdir):
    import asyncio
    from pathlib import Path

    from app.services import sandbox

    code, out, _ = asyncio.run(sandbox.run(
        "ls /workspace/src && echo made > /workspace/new.txt && "
        "(python -c 'import urllib.request;urllib.request.urlopen(\"http://1.1.1.1\",timeout=3)' "
        "&& echo NET_OK || echo NET_BLOCKED)",
        Path(workdir), None, 60,
    ))
    assert code == 0
    assert "a.py" in out
    assert "NET_BLOCKED" in out
    assert (Path(workdir) / "new.txt").read_text().strip() == "made"


@pytest.mark.integration
@pytest.mark.skipif(not _docker_ready(), reason="needs docker + python:3.12-slim image")
def test_real_container_timeout_kills_container(sandbox_on, workdir):
    import asyncio
    from pathlib import Path

    from app.services import sandbox

    code, _, _ = asyncio.run(sandbox.run("sleep 30", Path(workdir), None, 2))
    assert code is None
    left = subprocess.run(["docker", "ps", "-q", "--filter", "name=zenith-sbx-"], capture_output=True, text=True)
    assert left.stdout.strip() == ""
