"""Full backup-and-restore — the "one zip I can restore from if
something goes wrong" feature. Unlike `app/api/export.py` (a data
export of conversations/memories/etc as JSON/Markdown), this captures
the actual on-disk state: the SQLite database file itself, `config.json`,
and the full attachments/uploads directory tree. Restoring drops you
back to exactly where you were, including files.

Stdlib only (zipfile/sqlite3/shutil), matching export.py's philosophy.

WAL-safety: the app runs SQLite in WAL mode (see app/db/storage.py's
`_connect()`), so a raw `shutil.copy` of the .db file while the server
is live risks grabbing a torn/inconsistent snapshot (the real data can
still be sitting in the -wal file, uncheckpointed). We avoid that by
using `sqlite3.Connection.backup()` — the same API `sqlite3`'s own CLI
`.backup` command uses — which produces a guaranteed-consistent
snapshot regardless of WAL state, without needing to stop the server.
"""
from __future__ import annotations

import hashlib
import io
import json
import shutil
import sqlite3
import time
import zipfile
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from app.core.config import config_path as _config_path
from app.core.config import data_dir as _data_dir
from app.core.config import db_path as _db_path
from app.core.config import upload_dir as _upload_dir
from app.core.logging import get_logger

log = get_logger(__name__)
router = APIRouter(prefix="/api/backup", tags=["backup"])

# Internal zip layout — also used to sanity-check an uploaded zip before
# restoring from it.
DB_ARCNAME = "zenith.db"
CONFIG_ARCNAME = "config.json"
UPLOADS_PREFIX = "uploads/"

# A real Zenith backup must contain the DB file at minimum. config.json
# and uploads are optional (a fresh install may have no uploads yet, and
# config.json may not exist if the user never touched Settings).
REQUIRED_MEMBERS = {DB_ARCNAME}


def _consistent_db_snapshot(src: Path) -> bytes:
    """Returns bytes of a guaranteed-consistent snapshot of the live
    SQLite DB, using sqlite3's own backup API (checkpoints WAL content
    into the snapshot) rather than a raw file copy. Goes through a temp
    file — the same thing `sqlite3 db.db .backup` does under the hood —
    since serializing straight to bytes needs a newer sqlite3 lib than
    we want to depend on."""
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        _backup_db_to_path(src, tmp_path)
        return tmp_path.read_bytes()
    finally:
        tmp_path.unlink(missing_ok=True)


def _backup_db_to_path(src: Path, dst: Path) -> None:
    """Consistent snapshot of `src` written directly to `dst` via the
    sqlite3 backup API (no raw copy of a possibly-mid-write file)."""
    src_conn = sqlite3.connect(str(src))
    try:
        dst_conn = sqlite3.connect(str(dst))
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
    finally:
        src_conn.close()


def _build_backup_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        db_path = _db_path()
        if db_path.exists():
            zf.writestr(DB_ARCNAME, _consistent_db_snapshot(db_path))

        config_path = _config_path()
        if config_path.exists():
            zf.write(config_path, CONFIG_ARCNAME)

        checksums: dict[str, str] = {}
        if DB_ARCNAME in zf.namelist():
            checksums[DB_ARCNAME] = hashlib.sha256(zf.read(DB_ARCNAME)).hexdigest()
        upload_dir = _upload_dir()
        n_uploads, upload_bytes = 0, 0
        if upload_dir.exists():
            for f in upload_dir.rglob("*"):
                if f.is_file():
                    arcname = UPLOADS_PREFIX + str(f.relative_to(upload_dir))
                    zf.write(f, arcname)
                    n_uploads += 1
                    upload_bytes += f.stat().st_size

        manifest = {
            "created_at": time.time(),
            "app": "zenith",
            "kind": "full-backup",
            "format": 2,
            "app_version": _app_version(),
            "schema_version": _schema_version(db_path) if db_path.exists() else None,
            "attachments": {"files": n_uploads, "bytes": upload_bytes},
            "includes_config": config_path.exists(),
            "sha256": checksums,
        }
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
    return buf.getvalue()


@router.get("/create")
async def create_backup():
    """Streams a full backup zip: the SQLite database (consistent
    snapshot via sqlite3's backup API — safe even while the server is
    live and mid-write, see module docstring), `config.json`, and the
    entire attachments/uploads directory tree.

    This is a superset of `/api/export` — export.py gives you your data
    in an open, human-readable format; this gives you the exact bytes
    needed to restore the app to precisely where it was, files included.
    """
    payload = _build_backup_zip()
    filename = f"zenith-backup-{time.strftime('%Y-%m-%d')}.zip"
    return StreamingResponse(
        io.BytesIO(payload),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _app_version() -> str:
    from app.main import app as _app
    return str(_app.version)


def _schema_version(db: Path) -> int | None:
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            r = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
            return int(r[0]) if r and r[0] is not None else None
        finally:
            conn.close()
    except sqlite3.Error:
        return None


def _safe_upload_target(upload_dir: Path, name: str) -> Path | None:
    """Resolve an archive member under uploads/, refusing anything that
    would land outside it ("zip slip": ../ segments or absolute paths)."""
    rel = name[len(UPLOADS_PREFIX):]
    if not rel or rel.startswith(("/", "\\")) or ".." in Path(rel).parts:
        return None
    target = (upload_dir / rel).resolve()
    try:
        target.relative_to(upload_dir.resolve())
    except ValueError:
        return None
    return target


def inspect_backup(zf: zipfile.ZipFile) -> dict:
    """What restoring this archive would do, without touching anything:
    manifest, integrity (checksums + SQLite integrity_check), contents,
    and how it compares with the current install."""
    import tempfile

    names = zf.namelist()
    problems: list[str] = []
    manifest: dict = {}
    if "manifest.json" in names:
        try:
            manifest = json.loads(zf.read("manifest.json"))
        except (ValueError, zipfile.BadZipFile) as exc:
            problems.append(f"manifest.json is unreadable: {exc}")
    else:
        problems.append("No manifest — an older or hand-made backup; integrity can't be fully verified.")
    bad = zf.testzip()
    if bad:
        problems.append(f"Archive member {bad} is corrupt (CRC mismatch).")
    unsafe = [n for n in names if n.startswith(UPLOADS_PREFIX) and not n.endswith("/")
              and _safe_upload_target(_upload_dir(), n) is None]
    if unsafe:
        problems.append(f"{len(unsafe)} attachment path(s) point outside the uploads folder and will be skipped.")
    counts: dict[str, int] = {}
    schema = None
    if DB_ARCNAME in names:
        raw = zf.read(DB_ARCNAME)
        want = (manifest.get("sha256") or {}).get(DB_ARCNAME)
        if want and hashlib.sha256(raw).hexdigest() != want:
            problems.append("Database checksum doesn't match the manifest — the backup was modified or damaged.")
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp.write(raw)
            tmp_path = Path(tmp.name)
        try:
            conn = sqlite3.connect(str(tmp_path))
            try:
                ok = conn.execute("PRAGMA integrity_check").fetchone()[0]
                if ok != "ok":
                    problems.append(f"Database integrity check failed: {ok}")
                for table in ("conversations", "messages", "memories", "documents", "notes", "todos"):
                    try:
                        counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608
                    except sqlite3.Error:
                        pass
            finally:
                conn.close()
            schema = _schema_version(tmp_path)
        except sqlite3.DatabaseError as exc:
            problems.append(f"The database in this backup can't be opened: {exc}")
        finally:
            tmp_path.unlink(missing_ok=True)
    else:
        problems.append("Missing zenith.db — this isn't a Zenith backup.")
    current_schema = _schema_version(_db_path()) if _db_path().exists() else None
    notes = []
    if schema is not None and current_schema is not None and schema > current_schema:
        problems.append(f"This backup is from a newer Zenith (schema {schema} > {current_schema}). Update Zenith first.")
    elif schema is not None and current_schema is not None and schema < current_schema:
        notes.append(f"Older backup (schema {schema}); it will be upgraded to {current_schema} on the next start.")
    attachments = sum(1 for n in names if n.startswith(UPLOADS_PREFIX) and not n.endswith("/"))
    return {
        "ok": not any(p for p in problems if not p.startswith(("No manifest", f"{len(unsafe)} attachment"))),
        "problems": problems,
        "notes": notes,
        "created_at": manifest.get("created_at"),
        "app_version": manifest.get("app_version"),
        "schema_version": schema,
        "current_schema_version": current_schema,
        "counts": counts,
        "attachments": attachments,
        "includes_config": CONFIG_ARCNAME in names,
    }


@router.post("/inspect")
async def inspect_backup_upload(file: UploadFile):
    """Restore preview: validates an uploaded backup and reports what it holds."""
    raw = await file.read()
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        raise HTTPException(400, "That file isn't a zip archive.") from None
    with zf:
        return inspect_backup(zf)


def _validate_backup_zip(zf: zipfile.ZipFile) -> None:
    names = set(zf.namelist())
    missing = REQUIRED_MEMBERS - names
    if missing:
        raise HTTPException(
            400,
            f"Not a valid Zenith backup — missing expected file(s): {', '.join(sorted(missing))}.",
        )


def _snapshot_current_state(data_dir: Path) -> Path:
    """Copies the CURRENT live db/config/uploads into
    `<data_dir>/backup-before-restore-<timestamp>/` before a restore
    touches anything, so a bad restore is itself recoverable. Returns
    the snapshot directory."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    snapshot_dir = data_dir / f"backup-before-restore-{stamp}"
    snapshot_dir.mkdir(parents=True, exist_ok=False)

    db_path = _db_path()
    if db_path.exists():
        _backup_db_to_path(db_path, snapshot_dir / DB_ARCNAME)
        # Carry along -wal/-shm if present so the pre-restore snapshot is
        # itself fully restorable without relying only on the checkpoint.
        for suffix in ("-wal", "-shm"):
            side = db_path.with_name(db_path.name + suffix)
            if side.exists():
                shutil.copy2(side, snapshot_dir / (DB_ARCNAME + suffix))

    config_path = _config_path()
    if config_path.exists():
        shutil.copy2(config_path, snapshot_dir / CONFIG_ARCNAME)

    upload_dir = _upload_dir()
    if upload_dir.exists() and any(upload_dir.iterdir()):
        shutil.copytree(upload_dir, snapshot_dir / "uploads")

    return snapshot_dir


@router.post("/restore")
async def restore_backup(file: UploadFile, confirm: bool = Form(False)):
    """Restores the database, config.json, and uploads from a previously
    downloaded backup zip (see `/api/backup/create`).

    **DESTRUCTIVE**: this overwrites the live database, config.json, and
    attachments directory. Safety measures:
      1. Requires `confirm=true` in the multipart form body (matching
         `{"confirm": true}`'s intent for a multipart upload) — without
         it, this returns 400 and touches nothing.
      2. The uploaded zip is validated to actually look like a Zenith
         backup (must contain `zenith.db`) before anything destructive
         happens — a garbage/unrelated zip is rejected up front.
      3. Before overwriting anything, the CURRENT live state is itself
         snapshotted to `<data_dir>/backup-before-restore-<timestamp>/`,
         so a bad restore can be undone by hand.

    LIMITATION: any SQLite connections already open in this running
    process are not reloaded by this endpoint — restoring the file out
    from under a live connection pool is not attempted (a much harder,
    riskier problem than this endpoint needs to solve). **A restart of
    the backend process is required after calling this endpoint** for
    the restored database to actually take effect.
    """
    if not confirm:
        raise HTTPException(
            400,
            "Restore is destructive — pass confirm=true to proceed. Nothing was touched.",
        )

    raw = await file.read()
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        raise HTTPException(400, "Uploaded file is not a valid zip.") from None

    with zf:
        _validate_backup_zip(zf)
        report = inspect_backup(zf)
        if not report["ok"]:
            raise HTTPException(400, "Backup failed its integrity check — nothing was touched. " + " ".join(report["problems"]))

        data_dir = _data_dir()

        # 1. Safety net: snapshot current state before touching anything.
        snapshot_dir = _snapshot_current_state(data_dir)
        log.info("backup.restore_snapshot_created", path=str(snapshot_dir))

        # 2. Restore the DB file.
        db_path = _db_path()
        with zf.open(DB_ARCNAME) as src, open(db_path, "wb") as dst:
            shutil.copyfileobj(src, dst)
        # Drop any stale WAL/SHM side files from the pre-restore DB —
        # they refer to the old database and must not be replayed
        # against the newly-restored one.
        for suffix in ("-wal", "-shm"):
            side = db_path.with_name(db_path.name + suffix)
            side.unlink(missing_ok=True)

        # 3. Restore config.json, if present in the backup.
        if CONFIG_ARCNAME in zf.namelist():
            config_path = _config_path()
            with zf.open(CONFIG_ARCNAME) as src, open(config_path, "wb") as dst:
                shutil.copyfileobj(src, dst)

        # 4. Restore uploads: wipe the current directory, then extract.
        upload_dir = _upload_dir()
        if upload_dir.exists():
            shutil.rmtree(upload_dir)
        upload_dir.mkdir(parents=True, exist_ok=True)
        for name in zf.namelist():
            if name.startswith(UPLOADS_PREFIX) and not name.endswith("/"):
                target = _safe_upload_target(upload_dir, name)
                if target is None:
                    log.warning("backup.restore_skipped_unsafe_path", name=name)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(name) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)

    log.info("backup.restored", pre_restore_snapshot=str(snapshot_dir))
    return {
        "status": "restored",
        "pre_restore_snapshot": str(snapshot_dir),
        "restart_required": True,
        "message": (
            "Restore complete. A backend restart is required for the "
            "restored database to take effect — existing connections in "
            "this running process are stale."
        ),
    }
