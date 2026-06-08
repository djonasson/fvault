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

# Track all temp dirs created by this process for cleanup on crash
_active_temp_dirs: set[str] = set()


def _get_temp_base() -> str | None:
    """Return the directory where fvault temp dirs are created."""
    return os.environ.get("XDG_RUNTIME_DIR")


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
        # Security: filter out absolute paths and path traversal
        members = []
        for m in tar.getmembers():
            if m.name.startswith("/") or ".." in m.name:
                continue
            members.append(m)
        tar.extractall(dest, members=members)


def create_vault(folder_path: str, vault_path: str, password: str):
    """Encrypt a folder into a .vault file."""
    folder_path = os.path.abspath(folder_path)
    if not os.path.isdir(folder_path):
        raise ValueError(f"Not a directory: {folder_path}")

    file_count = _count_files(folder_path)
    metadata = {
        "version": 1,
        "created": datetime.now(timezone.utc).isoformat(),
        "files_count": file_count,
        "folder_name": os.path.basename(folder_path),
    }
    meta_bytes = json.dumps(metadata).encode("utf-8")

    tar_data = _tar_folder(folder_path)
    salt, nonce, ciphertext = crypto.encrypt(tar_data, password)

    with open(vault_path, "wb") as f:
        f.write(MAGIC)
        f.write(salt)
        f.write(nonce)
        f.write(struct.pack(">I", len(meta_bytes)))
        f.write(meta_bytes)
        f.write(ciphertext)


def get_vault_info(vault_path: str) -> dict:
    """Read vault metadata without decrypting."""
    with open(vault_path, "rb") as f:
        magic = f.read(HEADER_SIZE)
        if magic != MAGIC:
            raise ValueError("Not a valid vault file")
        f.read(16)  # salt
        f.read(12)  # nonce
        meta_len = struct.unpack(">I", f.read(4))[0]
        meta_bytes = f.read(meta_len)

    metadata = json.loads(meta_bytes)
    metadata["file_size"] = os.path.getsize(vault_path)
    return metadata


def open_vault(vault_path: str, password: str) -> str:
    """Decrypt a vault to a temp directory. Returns the temp dir path."""
    with open(vault_path, "rb") as f:
        magic = f.read(HEADER_SIZE)
        if magic != MAGIC:
            raise ValueError("Not a valid vault file")
        salt = f.read(16)
        nonce = f.read(12)
        meta_len = struct.unpack(">I", f.read(4))[0]
        f.read(meta_len)  # skip metadata
        ciphertext = f.read()

    tar_data = crypto.decrypt(salt, nonce, ciphertext, password)

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
        "version": 1,
        "created": created,
        "modified": datetime.now(timezone.utc).isoformat(),
        "files_count": file_count,
        "folder_name": os.path.basename(vault_path).replace(".vault", ""),
    }
    meta_bytes = json.dumps(metadata).encode("utf-8")

    tar_data = _tar_folder(temp_dir)
    salt, nonce, ciphertext = crypto.encrypt(tar_data, password)

    # Write to temp file first, then rename (atomic on same filesystem)
    tmp_vault = vault_path + ".tmp"
    with open(tmp_vault, "wb") as f:
        f.write(MAGIC)
        f.write(salt)
        f.write(nonce)
        f.write(struct.pack(">I", len(meta_bytes)))
        f.write(meta_bytes)
        f.write(ciphertext)

    os.replace(tmp_vault, vault_path)
