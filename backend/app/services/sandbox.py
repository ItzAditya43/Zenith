"""Optional container sandbox for agent shell commands (`agent_sandbox`).

Off by default — agent tools run as the backend's own OS user, which is the
documented trade-off (see README "Safety model"). With `agent_sandbox:
"docker"`, every bash / run_checks / shell_start command instead runs in a
throwaway container:

- only the conversation's working directory is visible, at /workspace (no
  working directory bound -> a private scratch dir under data/sandbox/);
- no network by default (`agent_sandbox_network: "none"`);
- all Linux capabilities dropped, no-new-privileges, pid/memory/cpu caps;
- runs as your uid:gid, so files it writes are yours, not root's.

The file tools (read_file/write_file/edit_file/list_dir) run in-process,
not in the container, so sandbox mode also confines them to the same
workspace — otherwise "sandboxed" bash could be sidestepped with read_file
on ~/.ssh.

Two modes:

- `docker`: a throwaway container as above. Works anywhere Docker does.
- `bwrap` (Linux): bubblewrap namespaces, no daemon and no image. The system
  directories (/usr, /etc, ...) are mounted read-only, the working
  directory read-write at /workspace, a private /tmp, and nothing else of
  your home. Network is cut unless `agent_sandbox_network` is "bridge".
  Same contract as docker for the agent; much faster to start.

bwrap can't run inside the Docker deployment (Docker's seccomp blocks the
nested user namespaces it needs; see docs/NOT_BUILT.md), but that
deployment's container already is the boundary. On native and desktop
installs it works unprivileged.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import uuid
from pathlib import Path, PurePosixPath

from app.core.config import data_dir, settings

CONTAINER_WORKSPACE = "/workspace"


class SandboxError(RuntimeError):
    pass


def mode() -> str:
    m = str(settings.get("agent_sandbox", "off"))
    return m if m in ("docker", "bwrap") else "off"


def enabled() -> bool:
    return mode() != "off"


def bwrap_path() -> str | None:
    return shutil.which("bwrap")


def docker_path() -> str | None:
    return shutil.which("docker")


def status() -> dict:
    m = mode()
    available = {"docker": docker_path() is not None, "bwrap": bwrap_path() is not None, "off": True}[m]
    return {
        "ok": available,
        "mode": m,
        "docker_available": docker_path() is not None,
        "bwrap_available": bwrap_path() is not None,
        "image": settings.get("agent_sandbox_image"),
        "network": settings.get("agent_sandbox_network"),
    }


def workspace(conversation_id: str | None, workdir: str | None) -> Path:
    """The directory the container (and the file tools) may touch."""
    if workdir:
        return Path(workdir).resolve()
    scratch = data_dir() / "sandbox" / (conversation_id or "default")
    scratch.mkdir(parents=True, exist_ok=True)
    return scratch.resolve()


def confine(path: Path, root: Path) -> Path:
    """Resolve `path` (following symlinks) and require it to sit inside
    `root`. Raises SandboxError otherwise."""
    resolved = path.resolve()
    if resolved != root and root not in resolved.parents:
        raise SandboxError(f"{path} is outside the sandbox workspace ({root}).")
    return resolved


def container_cwd(cwd: str | None, root: Path) -> str:
    if not cwd:
        return CONTAINER_WORKSPACE
    p = Path(cwd)
    if not p.is_absolute():
        p = root / p
    rel = confine(p, root).relative_to(root)
    return str(PurePosixPath(CONTAINER_WORKSPACE) / PurePosixPath(*rel.parts))


def new_container_name() -> str:
    return f"zenith-sbx-{uuid.uuid4().hex[:12]}"


_BWRAP_RO = ("/usr", "/etc", "/bin", "/sbin", "/lib", "/lib64", "/lib32", "/opt", "/nix", "/run/current-system")


def _bwrap_argv(command: str, root: Path, cwd: str | None) -> list[str]:
    bwrap = bwrap_path()
    if not bwrap:
        raise SandboxError(
            "Agent sandbox is set to bubblewrap but `bwrap` isn't installed. Install bubblewrap "
            "or pick another sandbox in Settings → Agent tools."
        )
    argv = [bwrap, "--die-with-parent", "--new-session", "--unshare-all"]
    if str(settings.get("agent_sandbox_network", "none")) != "none":
        argv.append("--share-net")
        for f in ("/etc/resolv.conf", "/etc/hosts"):
            argv += ["--ro-bind-try", f, f]
    for d in _BWRAP_RO:
        argv += ["--ro-bind-try", d, d]
    argv += [
        "--proc", "/proc", "--dev", "/dev",
        "--tmpfs", "/tmp",
        "--bind", str(root), CONTAINER_WORKSPACE,
        "--chdir", container_cwd(cwd, root),
        "--clearenv",
        "--setenv", "HOME", "/tmp",
        "--setenv", "PATH", "/usr/local/sbin:/usr/local/bin:/usr/bin:/usr/sbin:/bin:/sbin",
        "--setenv", "LANG", os.environ.get("LANG", "C.UTF-8"),
        "--setenv", "TERM", "xterm-256color",
        "sh", "-c", command,
    ]
    return argv


def build_argv(command: str, root: Path, cwd: str | None, name: str, interactive: bool = False) -> list[str]:
    if mode() == "bwrap":
        return _bwrap_argv(command, root, cwd)
    docker = docker_path()
    if not docker:
        raise SandboxError(
            "Agent sandbox is set to docker but the docker CLI isn't on PATH. "
            "Install Docker or turn the sandbox off in Settings → Agent tools."
        )
    argv = [
        docker, "run", "--rm", "--name", name,
        "--network", str(settings.get("agent_sandbox_network", "none")),
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--pids-limit", "512",
        "--memory", str(settings.get("agent_sandbox_memory", "2g")),
        "--cpus", str(settings.get("agent_sandbox_cpus", "2")),
        "--tmpfs", "/tmp:rw,exec,size=512m",
        "-e", "HOME=/tmp",
        "-v", f"{root}:{CONTAINER_WORKSPACE}",
        "-w", container_cwd(cwd, root),
    ]
    if interactive:
        argv.append("-i")
    if hasattr(os, "getuid"):
        argv += ["--user", f"{os.getuid()}:{os.getgid()}"]
    argv += [str(settings.get("agent_sandbox_image", "python:3.12-slim")), "sh", "-c", command]
    return argv


async def kill(name: str) -> None:
    """`docker run --rm` doesn't stop the container when its client is
    killed, so timeouts/shell_kill must stop it by name too. (bwrap
    sandboxes die with their parent, so there's nothing to do.)"""
    if mode() != "docker":
        return
    docker = docker_path()
    if not docker:
        return
    proc = await asyncio.create_subprocess_exec(
        docker, "kill", name, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        await asyncio.wait_for(proc.wait(), timeout=10)
    except TimeoutError:
        proc.kill()


async def run(command: str, root: Path, cwd: str | None, timeout: float, merge_stderr: bool = False):
    """Run one command to completion. Returns (exit_code, stdout, stderr);
    exit_code is None on timeout."""
    name = new_container_name()
    argv = build_argv(command, root, cwd, name)
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT if merge_stderr else asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        await kill(name)
        proc.kill()
        await proc.wait()
        return None, "", ""
    return proc.returncode, out.decode(errors="ignore"), (err or b"").decode(errors="ignore")


async def start(command: str, root: Path, cwd: str | None):
    """Start a long-lived command (shell sessions). Returns (proc, name)."""
    name = new_container_name()
    argv = build_argv(command, root, cwd, name, interactive=True)
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        stdin=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    return proc, name
