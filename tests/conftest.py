"""Shared fixtures for fvault tests."""

import json
import os
import struct

import pytest

import crypto
import vault


# ---------------------------------------------------------------------------
# Fast scrypt: reduce N from 2**20 to 2**14 so tests run in milliseconds
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True, scope="session")
def fast_scrypt():
    original = crypto.SCRYPT_N
    crypto.SCRYPT_N = 2**14
    yield
    crypto.SCRYPT_N = original


# ---------------------------------------------------------------------------
# Common fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_password():
    return "test-password-123"


@pytest.fixture
def vault_path(tmp_path):
    return tmp_path / "test.vault"


@pytest.fixture
def sample_folder(tmp_path):
    """Create a temp directory with a few test files."""
    folder = tmp_path / "sample"
    folder.mkdir()

    (folder / "hello.txt").write_text("Hello, world!\n")
    (folder / "data.bin").write_bytes(os.urandom(256))

    sub = folder / "subdir"
    sub.mkdir()
    (sub / "nested.txt").write_text("nested content\n")

    return folder


@pytest.fixture
def monkeypatch_config_dir(tmp_path, monkeypatch):
    """Redirect config.py to write inside tmp_path."""
    import config
    cfg_dir = str(tmp_path / "config")
    cfg_file = str(tmp_path / "config" / "config.json")
    monkeypatch.setattr(config, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(config, "CONFIG_FILE", cfg_file)
    return cfg_dir, cfg_file


@pytest.fixture
def monkeypatch_temp_base(tmp_path, monkeypatch):
    """Redirect vault temp dirs inside tmp_path and clean up after."""
    temp_base = tmp_path / "runtime"
    temp_base.mkdir()
    monkeypatch.setattr(vault, "_get_temp_base", lambda: str(temp_base))
    vault._active_temp_dirs.clear()
    yield str(temp_base)
    # Teardown: release any leftover temp dirs
    vault.cleanup_active_temp_dirs()


# ---------------------------------------------------------------------------
# Helper: craft a vault file with arbitrary metadata (for corruption tests)
# ---------------------------------------------------------------------------

def craft_vault_file(path, *, password="test-password-123",
                     magic=None, metadata_override=None,
                     meta_len_override=None, ciphertext=None):
    """Write a vault file with optional overrides for testing edge cases.

    By default creates a valid vault containing an empty tar.gz.
    """
    import io
    import tarfile

    if magic is None:
        magic = vault.MAGIC

    # Build metadata
    meta_dict = {"version": vault.CURRENT_VERSION, "created": "2026-01-01T00:00:00+00:00",
                 "files_count": 0, "folder_name": "test"}
    if metadata_override:
        meta_dict.update(metadata_override)
    meta_bytes = json.dumps(meta_dict).encode("utf-8")

    # Build ciphertext if not provided
    if ciphertext is None:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            pass  # empty tar
        pw_buf = bytearray(password.encode("utf-8"))
        salt, nonce, ciphertext = crypto.encrypt(buf.getvalue(), pw_buf, aad=meta_bytes)
        crypto.wipe(pw_buf)
    else:
        salt = os.urandom(16)
        nonce = os.urandom(12)

    meta_len = meta_len_override if meta_len_override is not None else len(meta_bytes)

    with open(str(path), "wb") as f:
        f.write(magic)
        f.write(salt)
        f.write(nonce)
        f.write(struct.pack(">I", meta_len))
        f.write(meta_bytes)
        f.write(ciphertext)
