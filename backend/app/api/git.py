"""Git and GitHub for the workspace's Changes tab (see git_workspace.py).

  GET  /api/conversations/{id}/git                  status: branch, staged, unstaged
  GET  /api/conversations/{id}/git/file-diff        diff of one file (?path=&staged=)
  GET  /api/conversations/{id}/git/log
  GET  /api/conversations/{id}/git/branches
  POST /api/conversations/{id}/git/stage            {paths}
  POST /api/conversations/{id}/git/unstage          {paths}
  POST /api/conversations/{id}/git/commit           {message}
  POST /api/conversations/{id}/git/switch           {name, create}
  POST /api/conversations/{id}/git/push
  GET  /api/conversations/{id}/github               gh installed / logged in
  GET  /api/conversations/{id}/github/issues
  GET  /api/conversations/{id}/github/issues/{n}
  GET  /api/conversations/{id}/github/pulls
  POST /api/conversations/{id}/github/pulls         {title, body, base, draft}

All scoped to the conversation's working folder, like the files API.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import Field

from app.api.files import _workdir
from app.models.schemas import StrictModel
from app.services import git_workspace as gw

router = APIRouter(prefix="/api", tags=["git"])


class PathsRequest(StrictModel):
    paths: list[str] = Field(min_length=1, max_length=2000)


class CommitRequest(StrictModel):
    message: str = Field(min_length=1, max_length=20_000)


class SwitchRequest(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    create: bool = False


class WorktreeRequest(StrictModel):
    name: str = Field(min_length=1, max_length=80)


class WorktreeRemove(StrictModel):
    path: str = Field(min_length=1, max_length=4000)


class PullRequest(StrictModel):
    title: str = Field(min_length=1, max_length=300)
    body: str = Field(default="", max_length=60_000)
    base: str = Field(default="", max_length=200)
    draft: bool = False


async def _call(coro):
    try:
        return await coro
    except gw.GitError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/conversations/{cid}/git")
async def git_state(cid: str):
    return await _call(gw.status(_workdir(cid)))


@router.get("/conversations/{cid}/git/file-diff")
async def file_diff(cid: str, path: str = Query(..., min_length=1), staged: bool = False):
    return {"diff": await _call(gw.diff(_workdir(cid), path, staged))}


@router.get("/conversations/{cid}/git/log")
async def git_log(cid: str, count: int = Query(20, ge=1, le=100)):
    return {"commits": await _call(gw.log(_workdir(cid), count))}


@router.get("/conversations/{cid}/git/branches")
async def git_branches(cid: str):
    return await _call(gw.branches(_workdir(cid)))


@router.post("/conversations/{cid}/git/stage")
async def git_stage(cid: str, body: PathsRequest):
    root = _workdir(cid)
    await _call(gw.stage(root, body.paths))
    return await _call(gw.status(root))


@router.post("/conversations/{cid}/git/unstage")
async def git_unstage(cid: str, body: PathsRequest):
    root = _workdir(cid)
    await _call(gw.unstage(root, body.paths))
    return await _call(gw.status(root))


@router.post("/conversations/{cid}/git/commit")
async def git_commit(cid: str, body: CommitRequest):
    root = _workdir(cid)
    summary = await _call(gw.commit(root, body.message))
    return {"commit": summary, "status": await _call(gw.status(root))}


@router.post("/conversations/{cid}/git/switch")
async def git_switch(cid: str, body: SwitchRequest):
    root = _workdir(cid)
    await _call(gw.switch_branch(root, body.name, body.create))
    return await _call(gw.status(root))


@router.post("/conversations/{cid}/git/push")
async def git_push(cid: str):
    root = _workdir(cid)
    output = await _call(gw.push(root))
    return {"output": output, "status": await _call(gw.status(root))}


@router.get("/conversations/{cid}/github")
async def github_state(cid: str):
    return await gw.gh_status(_workdir(cid))


@router.get("/conversations/{cid}/github/issues")
async def github_issues(cid: str):
    return {"issues": await _call(gw.issues(_workdir(cid)))}


@router.get("/conversations/{cid}/github/issues/{number}")
async def github_issue(cid: str, number: int):
    return await _call(gw.issue(_workdir(cid), number))


@router.get("/conversations/{cid}/github/pulls")
async def github_pulls(cid: str):
    return {"pulls": await _call(gw.pulls(_workdir(cid)))}


@router.post("/conversations/{cid}/github/pulls")
async def github_create_pr(cid: str, body: PullRequest):
    url = await _call(gw.create_pr(_workdir(cid), body.title, body.body, body.base, body.draft))
    return {"url": url}


@router.get("/conversations/{cid}/git/worktrees")
async def worktrees(cid: str):
    return {"worktrees": await _call(gw.list_worktrees(_workdir(cid)))}


@router.post("/conversations/{cid}/git/worktrees")
async def new_worktree(cid: str, body: WorktreeRequest):
    """Separate checkout on a new branch, plus a new chat bound to it (in the
    same project) where the agent can work without touching this folder."""
    from app.db import storage

    wt = await _call(gw.create_worktree(_workdir(cid), body.name))
    source = storage.get_conversation(cid) or {}
    conv = storage.create_conversation(body.name.strip()[:80])
    storage.set_conversation_workdir(conv["id"], wt["path"])
    if source.get("project_id"):
        try:
            storage.set_conversation_project(conv["id"], source["project_id"])
        except Exception:
            pass
    return {**wt, "conversation_id": conv["id"]}


@router.post("/conversations/{cid}/git/worktrees/remove")
async def drop_worktree(cid: str, body: WorktreeRemove):
    await _call(gw.remove_worktree(_workdir(cid), body.path))
    return {"removed": body.path}
