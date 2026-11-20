"""Desktop control status and setup (see app/services/desktop_control.py).

  GET  /api/desktop/status          which methods work on this machine
  POST /api/desktop/accessibility   {enabled}: let apps expose their buttons to Zenith
"""
from __future__ import annotations

import shutil

from fastapi import APIRouter, HTTPException, Request

from app.core.security import is_local_client
from app.models.schemas import StrictModel
from app.services import desktop_control as dc

router = APIRouter(prefix="/api/desktop", tags=["desktop"])


class AccessibilityBody(StrictModel):
    enabled: bool


async def _a11y_setting() -> bool | None:
    if not shutil.which("gsettings"):
        return None
    try:
        code, out, _ = await dc._run("gsettings", "get", "org.gnome.desktop.interface", "toolkit-accessibility")
    except dc.DesktopError:
        return None
    return out.strip() == "true" if code == 0 else None


@router.get("/status")
async def desktop_status():
    return {**dc.status(), "accessibility_on": await _a11y_setting()}


@router.post("/accessibility")
async def set_accessibility(body: AccessibilityBody, request: Request):
    """Turn the desktop's 'toolkit accessibility' on or off. On: GTK and
    Qt apps started afterwards expose their buttons and fields (the same
    setting screen readers use), so the agent can press them by name."""
    if not is_local_client(request.client.host if request.client else None):
        raise HTTPException(403, "Only from this machine.")
    if not shutil.which("gsettings"):
        raise HTTPException(409, "gsettings isn't available on this system.")
    code, _, err = await dc._run("gsettings", "set", "org.gnome.desktop.interface", "toolkit-accessibility",
                                 "true" if body.enabled else "false")
    if code != 0:
        raise HTTPException(409, err.strip() or "Couldn't change the setting.")
    return {"accessibility_on": await _a11y_setting()}
