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
    if not os.path.exists(CONFIG_FILE):
        return {"recent_vaults": []}
    with open(CONFIG_FILE) as f:
        return json.load(f)


def _save(data: dict):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)


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
