# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

fvault — a GTK 3 desktop app for encrypting folders into single `.vault` files using AES-256-GCM with scrypt key derivation. Python 3.10+, no test suite, no build step.

## Running

```bash
python3 fvault.py                # launch GUI
python3 fvault.py /path/to.vault # open a vault directly
./install.sh                     # system install to ~/.local
./uninstall.sh                   # remove system install
```

Dependencies: `cryptography>=41.0`, GTK 3 via PyGObject (`python3-gi`, `gir1.2-gtk-3.0`).

## Architecture

Single-process GTK 3 app with no build system. All modules are in the repo root and imported directly.

- **`fvault.py`** — Entry point. `FVaultApp` (Gtk.Application) and `FVaultWindow` (Gtk.ApplicationWindow). Manages the home screen (create/open/recent vaults) and browser view. Runs crypto operations in background threads with `_run_with_spinner`, posting results back to GTK via `GLib.idle_add`.
- **`vault.py`** — Binary `.vault` format: pack folder → tar.gz → AES-256-GCM encrypt. Handles create, open, save, and metadata reading. Manages temp directory lifecycle (creation, PID files, stale cleanup on startup, active cleanup on exit via `_active_temp_dirs` set).
- **`crypto.py`** — Thin wrapper around `cryptography` library. scrypt key derivation + AESGCM encrypt/decrypt. Passwords passed as `bytearray` and wiped after use.
- **`filebrowser.py`** — `FileBrowser(Gtk.Box)` widget: toolbar, breadcrumb path bar, TreeView with file operations (add/delete/rename/extract), drag-and-drop from system file manager, `xdg-open` for file viewing.
- **`dialogs.py`** — Password entry (with optional confirmation, min 8 chars), confirm/save-changes/error dialogs.
- **`config.py`** — Persists recent vaults list to `~/.config/fvault/config.json` (max 20 entries). Files written with `0o600` permissions.

## Key design details

- **Vault format v2**: Magic (`FVAULT\x01\x00`) + salt (16B) + nonce (12B) + metadata length (4B BE) + metadata JSON (cleartext, used as AAD) + encrypted tar.gz + GCM tag (16B). Metadata is integrity-protected via AAD but not encrypted.
- **Atomic saves**: Writes to `.tmp` then `os.replace()` to the real path.
- **Temp dir security**: Created in `$XDG_RUNTIME_DIR` (falls back to `/tmp`) with `0o700` permissions. Each has a `.fvault.pid` file. Cleanup happens via atexit, signal handlers (SIGTERM/SIGHUP/SIGINT), and stale sweep on startup.
- **Threading**: Crypto operations run in daemon threads; GTK updates dispatched via `GLib.idle_add`. No other concurrency.
