"""Vault format: pack/unpack folders into encrypted .vault files.

File format:
    [8 bytes magic: FVAULT\\x01\\x00]
    [16 bytes salt]
    [12 bytes nonce]
    [4 bytes metadata length (uint32 BE)]
    [metadata JSON]
    [AES-256-GCM encrypted tar.gz (includes 16-byte auth tag)]
"""

import glob
import io
import json
import os
import struct
import tarfile
import tempfile
from datetime import datetime, timezone

import crypto

MAGIC = b"FVAULT\x01\x00"
HEADER_SIZE = len(MAGIC)  # 8
META_MAX_SIZE = 1024 * 1024  # 1 MB — far more than any real metadata needs
CURRENT_VERSION = 2  # v2: metadata authenticated as AAD in AES-GCM


class IncompatibleVaultError(Exception):
    """Raised when a vault was created with an incompatible format version."""
    pass

# Track all temp dirs created by this process for cleanup on crash
_active_temp_dirs: set[str] = set()


def _get_temp_base() -> str | None:
    """Return the directory where fvault temp dirs are created.

    Prefers XDG_RUNTIME_DIR (typically a user-private tmpfs).
    Falls back to /tmp with a warning.
    """
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir and os.path.isdir(runtime_dir):
        return runtime_dir
    import warnings
    warnings.warn(
        "XDG_RUNTIME_DIR is not set. Decrypted files will be written to /tmp "
        "which may not be a tmpfs — data could persist on disk after deletion.",
        stacklevel=2,
    )
    return None


def cleanup_stale_temp_dirs():
    """Remove fvault-* temp dirs left behind by crashed sessions.

    Called at startup. Only removes dirs owned by the current user that
    have no corresponding live fvault process (checked via a PID file
    inside each temp dir).
    """
    base = _get_temp_base() or tempfile.gettempdir()
    pattern = os.path.join(base, "fvault-*")
    for path in glob.glob(pattern):
        if not os.path.isdir(path):
            continue
        pidfile = os.path.join(path, ".fvault.pid")
        if os.path.exists(pidfile):
            try:
                pid = int(open(pidfile).read().strip())
                os.kill(pid, 0)  # check if process is alive (signal 0)
                continue  # process is still running, skip
            except (ValueError, OSError, ProcessLookupError):
                pass  # PID invalid or process dead — stale dir
        # No pidfile or stale PID — clean it up
        import shutil
        shutil.rmtree(path, ignore_errors=True)


def cleanup_active_temp_dirs():
    """Remove all temp dirs created by THIS process. Called by atexit/signal."""
    import shutil
    for path in list(_active_temp_dirs):
        if os.path.exists(path):
            shutil.rmtree(path, ignore_errors=True)
        _active_temp_dirs.discard(path)


def _count_files(folder_path: str) -> int:
    count = 0
    for _, _, files in os.walk(folder_path):
        count += len(files)
    return count


def _tar_folder(folder_path: str) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for entry in sorted(os.listdir(folder_path)):
            tar.add(os.path.join(folder_path, entry), arcname=entry)
    return buf.getvalue()


def _untar_to(data: bytes, dest: str):
    buf = io.BytesIO(data)
    with tarfile.open(fileobj=buf, mode="r:gz") as tar:
        tar.extractall(dest, filter="data")


def create_vault(folder_path: str, vault_path: str, password: str):
    """Encrypt a folder into a .vault file."""
    folder_path = os.path.abspath(folder_path)
    if not os.path.isdir(folder_path):
        raise ValueError(f"Not a directory: {folder_path}")

    file_count = _count_files(folder_path)
    metadata = {
        "version": CURRENT_VERSION,
        "created": datetime.now(timezone.utc).isoformat(),
        "files_count": file_count,
        "folder_name": os.path.basename(folder_path),
    }
    meta_bytes = json.dumps(metadata).encode("utf-8")

    pw_buf = bytearray(password.encode("utf-8"))
    try:
        tar_data = _tar_folder(folder_path)
        salt, nonce, ciphertext = crypto.encrypt(tar_data, pw_buf, aad=meta_bytes)
    finally:
        crypto.wipe(pw_buf)

    fd = os.open(vault_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(MAGIC)
        f.write(salt)
        f.write(nonce)
        f.write(struct.pack(">I", len(meta_bytes)))
        f.write(meta_bytes)
        f.write(ciphertext)


def _read_header(f) -> tuple[bytes, bytes, bytes]:
    """Read and validate vault header. Returns (salt, nonce, meta_bytes)."""
    magic = f.read(HEADER_SIZE)
    if magic != MAGIC:
        raise ValueError("Not a valid vault file")
    salt = f.read(16)
    nonce = f.read(12)
    meta_len = struct.unpack(">I", f.read(4))[0]
    if meta_len > META_MAX_SIZE:
        raise ValueError(f"Metadata too large ({meta_len} bytes) — file may be corrupt")
    meta_bytes = f.read(meta_len)
    return salt, nonce, meta_bytes


def get_vault_info(vault_path: str) -> dict:
    """Read vault metadata without decrypting."""
    with open(vault_path, "rb") as f:
        _, _, meta_bytes = _read_header(f)

    metadata = json.loads(meta_bytes)
    metadata["file_size"] = os.path.getsize(vault_path)
    return metadata


def open_vault(vault_path: str, password: str) -> str:
    """Decrypt a vault to a temp directory. Returns the temp dir path."""
    with open(vault_path, "rb") as f:
        salt, nonce, meta_bytes = _read_header(f)
        ciphertext = f.read()

    meta = json.loads(meta_bytes)
    vault_version = meta.get("version", 1)
    if vault_version < CURRENT_VERSION:
        raise IncompatibleVaultError(
            f"This vault was created with format version {vault_version} "
            f"and cannot be opened by this version of fvault (requires version "
            f"{CURRENT_VERSION}). Recreate the vault or use the original version "
            f"of fvault that created it to recover the files."
        )
    if vault_version > CURRENT_VERSION:
        raise IncompatibleVaultError(
            f"This vault was created with a newer format (version {vault_version}). "
            f"Update fvault to open it."
        )

    pw_buf = bytearray(password.encode("utf-8"))
    try:
        tar_data = crypto.decrypt(salt, nonce, ciphertext, pw_buf, aad=meta_bytes)
    finally:
        crypto.wipe(pw_buf)

    runtime_dir = _get_temp_base()
    temp_dir = tempfile.mkdtemp(prefix="fvault-", dir=runtime_dir)
    os.chmod(temp_dir, 0o700)

    # Write PID file so cleanup_stale_temp_dirs() can tell live from dead
    with open(os.path.join(temp_dir, ".fvault.pid"), "w") as pf:
        pf.write(str(os.getpid()))

    _active_temp_dirs.add(temp_dir)
    _untar_to(tar_data, temp_dir)
    return temp_dir


def save_vault(temp_dir: str, vault_path: str, password: str):
    """Re-encrypt a temp directory back into a vault file."""
    # Read existing metadata to preserve creation date
    try:
        old_meta = get_vault_info(vault_path)
        created = old_meta.get("created", datetime.now(timezone.utc).isoformat())
    except (FileNotFoundError, ValueError):
        created = datetime.now(timezone.utc).isoformat()

    file_count = _count_files(temp_dir)
    metadata = {
        "version": CURRENT_VERSION,
        "created": created,
        "modified": datetime.now(timezone.utc).isoformat(),
        "files_count": file_count,
        "folder_name": os.path.basename(vault_path).replace(".vault", ""),
    }
    meta_bytes = json.dumps(metadata).encode("utf-8")

    pw_buf = bytearray(password.encode("utf-8"))
    try:
        tar_data = _tar_folder(temp_dir)
        salt, nonce, ciphertext = crypto.encrypt(tar_data, pw_buf, aad=meta_bytes)
    finally:
        crypto.wipe(pw_buf)

    # Write to temp file first, then rename (atomic on same filesystem)
    tmp_vault = vault_path + ".tmp"
    fd = os.open(tmp_vault, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(MAGIC)
        f.write(salt)
        f.write(nonce)
        f.write(struct.pack(">I", len(meta_bytes)))
        f.write(meta_bytes)
        f.write(ciphertext)

    os.replace(tmp_vault, vault_path)
