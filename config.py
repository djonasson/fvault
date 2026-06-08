"""Persistent config: recent vaults list."""

import json
import os

CONFIG_DIR = os.path.join(
    os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
    "fvault",
)
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
MAX_RECENT = 20


def _load() -> dict:
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"recent_vaults": []}


def _save(data: dict):
    os.makedirs(CONFIG_DIR, mode=0o700, exist_ok=True)
    os.chmod(CONFIG_DIR, 0o700)
    fd = os.open(CONFIG_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
    os.chmod(CONFIG_FILE, 0o600)


def get_recent_vaults() -> list[str]:
    return _load().get("recent_vaults", [])


def add_recent_vault(path: str):
    path = os.path.abspath(path)
    data = _load()
    recents = data.get("recent_vaults", [])
    if path in recents:
        recents.remove(path)
    recents.insert(0, path)
    data["recent_vaults"] = recents[:MAX_RECENT]
    _save(data)


def remove_recent_vault(path: str):
    path = os.path.abspath(path)
    data = _load()
    recents = data.get("recent_vaults", [])
    if path in recents:
        recents.remove(path)
        data["recent_vaults"] = recents
        _save(data)
