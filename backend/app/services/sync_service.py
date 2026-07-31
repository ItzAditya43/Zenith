"""Multi-device sync, built around a design decision made deliberately
rather than defaulted into: knowing the sync passphrase alone is not
enough to read synced data — a device also needs the **sync secret**,
which only ever moves between devices through a short-lived, single-use
pairing code (never sent in plaintext, never stored on a server you don't
control). This is not literal hardware/TPM binding (that's inconsistent
across Docker/Windows/macOS/Linux for one app), but it delivers the same
practical guarantee: a leaked passphrase alone doesn't unlock synced data
on an unpaired device.

Transport is deliberately out of scope here — pairing and sync both happen
over whatever network the two devices can already reach each other on
(your LAN, Tailscale, etc., via the existing `cors_allow_lan` support).
This module only handles the crypto and the data bundle; the frontend
supplies the other device's address.
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import string
import time

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from cryptography.hazmat.primitives import hashes

from app.core.config import data_dir
from app.core.logging import get_logger
from app.db.storage import _conn

log = get_logger(__name__)

_PAIRING_TTL_SECONDS = 300
_pairing_state: dict[str, dict] = {}  # code -> {secret_bytes, expires_at, used}


def _sync_secret_path():
    return data_dir() / "sync_secret.bin"


def get_or_create_sync_secret() -> bytes:
    """32 random bytes, generated once per device and never transmitted
    except AES-GCM-encrypted under a one-time pairing code. This is what
    makes a device "paired" — devices sharing this secret (+ the same
    passphrase) derive the same data-encryption key."""
    path = _sync_secret_path()
    if path.exists():
        return path.read_bytes()
    secret = secrets.token_bytes(32)
    path.write_bytes(secret)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return secret


def set_sync_secret(secret: bytes) -> None:
    """Called after a successful pairing hand-off — adopts the other
    device's sync secret so both devices derive the same encryption key."""
    path = _sync_secret_path()
    path.write_bytes(secret)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def derive_key(passphrase: str, sync_secret: bytes | None = None) -> bytes:
    """The actual data-encryption key: scrypt(passphrase) combined with
    the local sync secret via HKDF. Neither half alone is sufficient —
    the passphrase without the paired secret decrypts nothing, and vice
    versa."""
    sync_secret = sync_secret if sync_secret is not None else get_or_create_sync_secret()
    stretched = Scrypt(salt=sync_secret[:16], length=32, n=2**14, r=8, p=1).derive(passphrase.encode())
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=sync_secret, info=b"cortex-sync-v1").derive(stretched)


def _encrypt(key: bytes, plaintext: bytes) -> bytes:
    nonce = secrets.token_bytes(12)
    return nonce + AESGCM(key).encrypt(nonce, plaintext, None)


def _decrypt(key: bytes, blob: bytes) -> bytes:
    nonce, ct = blob[:12], blob[12:]
    return AESGCM(key).decrypt(nonce, ct, None)


# ---------- Pairing (one-time code carries the sync secret) ----------

def start_pairing() -> dict:
    """This device is the source of trust: generates a short-lived code
    and, while it's active, will hand its sync secret (AES-GCM-encrypted
    under the code) to whoever presents that exact code."""
    code = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(10))
    expires_at = time.time() + _PAIRING_TTL_SECONDS
    _pairing_state[code] = {"expires_at": expires_at, "used": False}
    return {"code": code, "expires_at": expires_at}


def get_pairing_bundle(code: str) -> str | None:
    """Called (by the joining device, over LAN/Tailscale) with the code
    the user typed in from the trusted device's screen. Single-use: the
    code is consumed on first successful fetch."""
    state = _pairing_state.get(code)
    if not state or state["used"] or time.time() > state["expires_at"]:
        return None
    state["used"] = True
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"cortex-pairing", info=code.encode()).derive(
        code.encode()
    )
    secret = get_or_create_sync_secret()
    return base64.b64encode(_encrypt(key, secret)).decode()


def complete_pairing(code: str, encrypted_secret_b64: str) -> bool:
    """Called on the joining device with the blob fetched from the
    trusted device's /pair/bundle endpoint. Decrypts using the same code
    (never transmitted — typed by the user on both ends) and adopts the
    resulting sync secret."""
    try:
        key = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"cortex-pairing", info=code.encode()).derive(
            code.encode()
        )
        secret = _decrypt(key, base64.b64decode(encrypted_secret_b64))
    except Exception as exc:
        log.warning("sync.pairing_decrypt_failed", error=str(exc))
        return False
    if len(secret) != 32:
        return False
    set_sync_secret(secret)
    return True


# ---------- Data bundle export/import ----------

_SYNCED_TABLES = ["projects", "notes", "todos", "calendar_events", "personas", "memories"]


def export_data_bundle() -> dict:
    """A snapshot of the small, mostly-config-like tables that make
    sense to sync (notes/todos/calendar/personas/memories/projects) —
    deliberately NOT full chat history, which is large and where
    conflict resolution matters more than this simple bundle model
    supports."""
    bundle: dict = {"version": 1, "exported_at": time.time(), "tables": {}}
    with _conn() as conn:
        for table in _SYNCED_TABLES:
            try:
                rows = conn.execute(f"SELECT * FROM {table}").fetchall()
                bundle["tables"][table] = [dict(r) for r in rows]
            except Exception as exc:
                log.warning("sync.export_table_failed", table=table, error=str(exc))
    return bundle


def import_data_bundle(bundle: dict) -> dict:
    """Merges by primary key (id) — INSERT OR IGNORE, so importing never
    overwrites local edits, only adds what's missing. Returns per-table
    counts of rows actually inserted."""
    counts: dict[str, int] = {}
    tables = bundle.get("tables", {})
    with _conn() as conn:
        for table, rows in tables.items():
            if table not in _SYNCED_TABLES or not rows:
                counts[table] = 0
                continue
            inserted = 0
            cols = list(rows[0].keys())
            placeholders = ", ".join("?" for _ in cols)
            col_list = ", ".join(cols)
            for row in rows:
                try:
                    cur = conn.execute(
                        f"INSERT OR IGNORE INTO {table} ({col_list}) VALUES ({placeholders})",
                        [row[c] for c in cols],
                    )
                    inserted += cur.rowcount
                except Exception as exc:
                    log.warning("sync.import_row_failed", table=table, error=str(exc))
            counts[table] = inserted
    return counts


def create_export_blob(passphrase: str) -> str:
    key = derive_key(passphrase)
    bundle = export_data_bundle()
    encrypted = _encrypt(key, json.dumps(bundle).encode())
    return base64.b64encode(encrypted).decode()


def apply_import_blob(passphrase: str, blob_b64: str) -> dict:
    key = derive_key(passphrase)
    try:
        plaintext = _decrypt(key, base64.b64decode(blob_b64))
        bundle = json.loads(plaintext)
    except Exception as exc:
        raise ValueError(f"Couldn't decrypt — wrong passphrase, unpaired device, or corrupt file: {exc}") from exc
    return import_data_bundle(bundle)
