"""Visual workflows.

  GET    /api/workflows                      — list
  POST   /api/workflows                      — create/update {id?, name, graph}
  DELETE /api/workflows/{id}                 — remove (and its run history)
  GET    /api/workflows/{id}/runs            — recent runs with traces
  POST   /api/workflows/run                  — run a graph (SSE): {graph, input, workflow_id?}
  POST   /api/workflows/runs/{run}/review    — approve/reject a waiting review node
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.services import workflow_service as wf

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


class WorkflowSave(BaseModel):
    id: str | None = None
    name: str = Field(min_length=1, max_length=120)
    graph: dict


class RunBody(BaseModel):
    graph: dict
    input: str = Field(default="", max_length=20000)
    workflow_id: str | None = None


class ReviewBody(BaseModel):
    node_id: str
    approve: bool


@router.get("")
async def list_workflows():
    return wf.list_workflows()


@router.post("")
async def save_workflow(body: WorkflowSave):
    try:
        return wf.save_workflow(body.name.strip(), body.graph, body.id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete("/{workflow_id}")
async def delete_workflow(workflow_id: str):
    wf.delete_workflow(workflow_id)
    return {"ok": True}


@router.get("/{workflow_id}/runs")
async def runs(workflow_id: str):
    return wf.list_runs(workflow_id)


@router.post("/run")
async def run(body: RunBody):
    async def gen():
        async for ev in wf.run_workflow(body.graph, body.input, body.workflow_id):
            yield f"data: {json.dumps(ev)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/runs/{run_id}/review")
async def review(run_id: str, body: ReviewBody):
    if not wf.resolve_review(run_id, body.node_id, body.approve):
        raise HTTPException(404, "Nothing is waiting for review there.")
    return {"ok": True}
