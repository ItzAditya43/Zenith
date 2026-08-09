"""Encrypted-at-rest credentials — see crypto_service.py. Sensitive
config fields (email_password, auth_shared_secret) must be unreadable
in config.json on disk but transparently plaintext in memory."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


@pytest.fixture
def temp_data_dir(monkeypatch):
    d = tempfile.mkdtemp(prefix="cortex-test-")
    monkeypatch.setenv("CORTEX_DATA_DIR", d)
    from app.core import config as cfg

    cfg.refresh_paths()
    cfg.settings.reload()
    yield Path(d)
    cfg.refresh_paths()
    cfg.settings.reload()


def test_encrypt_decrypt_round_trip(temp_data_dir):
    from app.services import crypto_service

    ct = crypto_service.encrypt("hunter2")
    assert ct != "hunter2"
    assert crypto_service.is_encrypted(ct)
    assert crypto_service.decrypt(ct) == "hunter2"


def test_empty_string_passes_through(temp_data_dir):
    from app.services import crypto_service

    assert crypto_service.encrypt("") == ""
    assert crypto_service.decrypt("") == ""


def test_plaintext_is_not_treated_as_encrypted(temp_data_dir):
    from app.services import crypto_service

    assert crypto_service.is_encrypted("plain-secret") is False
    assert crypto_service.decrypt("plain-secret") == "plain-secret"


def test_key_file_created_with_restrictive_permissions(temp_data_dir):
    from app.services import crypto_service

    crypto_service.encrypt("x")
    key_path = temp_data_dir / ".machine_key"
    assert key_path.exists()
    mode = key_path.stat().st_mode & 0o777
    assert mode == 0o600


def test_config_save_encrypts_sensitive_fields_on_disk(temp_data_dir):
    from app.core import config as cfg

    cfg.settings.set("email_password", "supersecret123")
    cfg.settings.set("auth_shared_secret", "topsecret456")

    raw = json.loads(cfg.config_path().read_text())
    assert raw["email_password"] != "supersecret123"
    assert raw["email_password"].startswith("enc:v1:")
    assert raw["auth_shared_secret"].startswith("enc:v1:")

    # In-memory access stays plaintext.
    assert cfg.settings.get("email_password") == "supersecret123"


def test_config_reload_decrypts_transparently(temp_data_dir):
    from app.core import config as cfg

    cfg.settings.set("email_password", "supersecret123")
    cfg.settings.reload()
    assert cfg.settings.get("email_password") == "supersecret123"


def test_non_sensitive_fields_stay_plaintext_on_disk(temp_data_dir):
    from app.core import config as cfg

    cfg.settings.set("system_prompt", "be concise")
    raw = json.loads(cfg.config_path().read_text())
    assert raw["system_prompt"] == "be concise"
