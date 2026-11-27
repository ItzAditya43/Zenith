"""Scheduled/recurring turns.

  GET    /api/schedules               — list
  POST   /api/schedules                — create {name, prompt, mode, interval_minutes}
  PATCH  /api/schedules/{id}           — enable/disable
  PUT    /api/schedules/{id}/timing    — change interval/daily/weekly timing
  DELETE /api/schedules/{id}           — remove (keeps its conversation and run history)
  GET    /api/schedules/{id}/runs      — run history
  POST   /api/schedules/{id}/run-now   — trigger immediately, waits for the result
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.core.logging import get_logger
from app.models.schemas import ScheduleCreate, ScheduleTiming, ScheduleToggle
from app.services import schedule_service

log = get_logger(__name__)
router = APIRouter(prefix="/api/schedules", tags=["schedules"])


@router.get("")
async def list_schedules():
    return schedule_service.list_schedules()


@router.post("")
async def create_schedule(body: ScheduleCreate):
    try:
        return schedule_service.create_schedule(body.name, body.prompt, body.mode, body.interval_minutes, body.todo_mode,
                                                kind=body.kind, time_of_day=body.time_of_day, weekdays=body.weekdays,
                                                timezone=body.timezone)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.put("/{schedule_id}/timing")
async def update_timing(schedule_id: str, body: ScheduleTiming):
    try:
        s = schedule_service.update_timing(schedule_id, kind=body.kind, interval_minutes=body.interval_minutes,
                                           time_of_day=body.time_of_day, weekdays=body.weekdays, timezone=body.timezone)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not s:
        raise HTTPException(404, "No such schedule.")
    return s


@router.patch("/{schedule_id}")
async def toggle_schedule(schedule_id: str, body: ScheduleToggle):
    if not schedule_service.get_schedule(schedule_id):
        raise HTTPException(404, "No such schedule.")
    schedule_service.set_enabled(schedule_id, body.enabled)
    return {"ok": True}


@router.delete("/{schedule_id}")
async def delete_schedule(schedule_id: str):
    schedule_service.delete_schedule(schedule_id)
    return {"ok": True}


@router.get("/recent-runs")
async def recent_runs(since: float = 0):
    """Completed runs across all schedules finished after `since` (unix ts).
    Polled by the frontend to raise desktop notifications for background
    scheduled tasks."""
    return schedule_service.list_recent_runs(since)


@router.get("/{schedule_id}/runs")
async def list_runs(schedule_id: str):
    return schedule_service.list_runs(schedule_id)


@router.post("/{schedule_id}/run-now")
async def run_now(schedule_id: str):
    schedule = schedule_service.get_schedule(schedule_id)
    if not schedule:
        raise HTTPException(404, "No such schedule.")
    return await schedule_service.run_schedule(schedule)
