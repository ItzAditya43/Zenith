"""Multi-device sync — pairing (device-bound secret hand-off) and
encrypted export/import of the small sync-able tables. See
app/services/sync_service.py for the design rationale.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.core.logging import get_logger
from app.services import sync_service

log = get_logger(__name__)
router = APIRouter(prefix="/api/sync", tags=["sync"])


@router.post("/pair/start")
async def pair_start():
    """Run this on the device you already trust. Shows a code on
    screen — type it into the new device within 5 minutes."""
    return sync_service.start_pairing()


@router.get("/pair/bundle")
async def pair_bundle(code: str):
    """Fetched by the joining device (it must reach this device over
    your LAN/Tailscale/etc). Returns the encrypted sync secret, or 404
    if the code is wrong, expired, or already used."""
    blob = sync_service.get_pairing_bundle(code)
    if blob is None:
        raise HTTPException(404, "Invalid, expired, or already-used pairing code.")
    return {"encrypted_secret": blob}


@router.post("/pair/complete")
async def pair_complete(body: dict):
    """Run on the joining device with the code (typed by the user) and
    the blob fetched from the trusted device's /pair/bundle."""
    code = str(body.get("code", "")).strip()
    encrypted_secret = str(body.get("encrypted_secret", "")).strip()
    if not code or not encrypted_secret:
        raise HTTPException(422, "code and encrypted_secret are required.")
    ok = sync_service.complete_pairing(code, encrypted_secret)
    if not ok:
        raise HTTPException(400, "Pairing failed — wrong or expired code.")
    return {"ok": True}


@router.post("/export")
async def sync_export(body: dict):
    passphrase = str(body.get("passphrase", ""))
    if not passphrase:
        raise HTTPException(422, "passphrase is required.")
    return {"blob": sync_service.create_export_blob(passphrase)}


@router.post("/import")
async def sync_import(body: dict):
    passphrase = str(body.get("passphrase", ""))
    blob = str(body.get("blob", ""))
    if not passphrase or not blob:
        raise HTTPException(422, "passphrase and blob are required.")
    try:
        counts = sync_service.apply_import_blob(passphrase, blob)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True, "counts": counts}
