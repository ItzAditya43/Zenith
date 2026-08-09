"""Encrypted-at-rest storage for the sensitive fields in config.json
(currently: `email_password`, `auth_shared_secret`) — a scoped answer to
"encrypt data at rest", not a full-database rewrite.

The rest of the app's SQLite data (conversations, memories, documents)
stays exactly as documented in the Safety model: a login gate (passcode
lock), not at-rest encryption — doing that properly needs SQLCipher and
breaks FTS5 search, a tradeoff explicitly not taken on here. Credentials
are different: they're small, few, and don't need to be searchable, so
they can be encrypted with a local machine key without that tradeoff.

The key lives in `data/.machine_key` (generated once, 0600 permissions —
readable only by the OS user running Zenith). This means config.json's
encrypted fields are unreadable outside this machine/user account even
if the file itself is copied elsewhere or read by another local user —
a real improvement over the plaintext-in-a-JSON-file status quo, without
claiming protection this doesn't actually provide (anyone with the same
OS-user access as the running Zenith process can still read both the
key file and decrypt everything — this is data-at-rest-on-disk
protection, not protection from another process running as you).
"""
from __future__ import annotations

import base64
import logging
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import data_dir

# Plain stdlib logging, not app.core.logging.get_logger — this module is
# imported from inside config.py's own load/save path, and get_logger
# reads settings at import time, which would be a circular import right
# when config.py is still mid-construction of `settings` itself.
log = logging.getLogger(__name__)

# Config keys treated as credentials — encrypted on save, transparently
# decrypted on load. Extend this list if a future integration adds
# another secret (an API key, a second account password, ...).
SENSITIVE_KEYS = ("email_password", "auth_shared_secret")

_ENC_PREFIX = "enc:v1:"


def _key_path():
    return data_dir() / ".machine_key"


def _load_or_create_key() -> bytes:
    path = _key_path()
    if path.exists():
        return base64.b64decode(path.read_text().strip())
    key = AESGCM.generate_key(bit_length=256)
    path.write_text(base64.b64encode(key).decode())
    try:
        os.chmod(path, 0o600)
    except OSError as exc:
        log.warning("crypto.chmod_failed", error=str(exc))
    return key


def encrypt(plaintext: str) -> str:
    if not plaintext:
        return plaintext
    key = _load_or_create_key()
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, plaintext.encode(), None)
    return _ENC_PREFIX + base64.b64encode(nonce + ct).decode()


def decrypt(value: str) -> str:
    if not value or not value.startswith(_ENC_PREFIX):
        return value
    try:
        key = _load_or_create_key()
        raw = base64.b64decode(value[len(_ENC_PREFIX):])
        nonce, ct = raw[:12], raw[12:]
        return AESGCM(key).decrypt(nonce, ct, None).decode()
    except Exception as exc:
        log.warning("crypto.decrypt_failed", error=str(exc))
        return ""


def is_encrypted(value: str) -> bool:
    return isinstance(value, str) and value.startswith(_ENC_PREFIX)
