#!/bin/bash
set -euo pipefail

XDG_DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
APP_DIR="$XDG_DATA_HOME/fvault"
INSTALL_DIR="$HOME/.local/bin"
DESKTOP_DIR="$XDG_DATA_HOME/applications"
MIME_DIR="$XDG_DATA_HOME/mime/packages"
CONFIG_DIR="$XDG_CONFIG_HOME/fvault"

echo "=== fvault uninstaller ==="
echo

rm -f "$INSTALL_DIR/fvault"
rm -rf "$APP_DIR"
rm -f "$DESKTOP_DIR/fvault.desktop"
rm -f "$MIME_DIR/fvault-vault.xml"

update-mime-database "$XDG_DATA_HOME/mime" 2>/dev/null || true
update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true

echo "Removed fvault application files."

if [ -d "$CONFIG_DIR" ]; then
    read -p "Remove config ($CONFIG_DIR)? [y/N] " answer
    if [[ "$answer" =~ ^[Yy] ]]; then
        rm -rf "$CONFIG_DIR"
        echo "Config removed."
    else
        echo "Config kept."
    fi
fi

echo
echo "=== Uninstall complete ==="
