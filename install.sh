#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
XDG_DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
INSTALL_DIR="$HOME/.local/bin"
APP_DIR="$XDG_DATA_HOME/fvault"
DESKTOP_DIR="$XDG_DATA_HOME/applications"
MIME_DIR="$XDG_DATA_HOME/mime/packages"

echo "=== fvault installer ==="
echo

# Check Python 3
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 is required but not found."
    exit 1
fi

# Check/install GTK bindings
if ! python3 -c "import gi; gi.require_version('Gtk', '3.0'); from gi.repository import Gtk" 2>/dev/null; then
    echo "Installing GTK3 Python bindings..."
    sudo apt install -y python3-gi gir1.2-gtk-3.0
fi

# Check/install cryptography
if ! python3 -c "from cryptography.hazmat.primitives.ciphers.aead import AESGCM" 2>/dev/null; then
    echo "Installing cryptography library..."
    pip3 install --user cryptography
fi

echo "Dependencies OK"

# Install application files
echo "Installing fvault to $APP_DIR..."
mkdir -p "$APP_DIR" "$INSTALL_DIR"
cp "$SCRIPT_DIR"/crypto.py "$APP_DIR/"
cp "$SCRIPT_DIR"/vault.py "$APP_DIR/"
cp "$SCRIPT_DIR"/config.py "$APP_DIR/"
cp "$SCRIPT_DIR"/dialogs.py "$APP_DIR/"
cp "$SCRIPT_DIR"/filebrowser.py "$APP_DIR/"
cp "$SCRIPT_DIR"/fvault.py "$APP_DIR/"

# Create launcher script
cat > "$INSTALL_DIR/fvault" << 'LAUNCHER'
#!/bin/bash
_XDG_DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
exec python3 "$_XDG_DATA_HOME/fvault/fvault.py" "$@"
LAUNCHER
chmod +x "$INSTALL_DIR/fvault"

# Check PATH
if ! echo "$PATH" | tr ':' '\n' | grep -qx "$INSTALL_DIR"; then
    echo
    echo "WARNING: $INSTALL_DIR is not in your PATH."
    echo "Add this to your ~/.bashrc or ~/.zshrc:"
    echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
fi

# Install MIME type
echo "Registering .vault MIME type..."
mkdir -p "$MIME_DIR"
cp "$SCRIPT_DIR/desktop/fvault-vault.xml" "$MIME_DIR/"
update-mime-database "$XDG_DATA_HOME/mime" 2>/dev/null || true

# Install .desktop file
echo "Installing desktop entry..."
mkdir -p "$DESKTOP_DIR"
cp "$SCRIPT_DIR/desktop/fvault.desktop" "$DESKTOP_DIR/"
chmod +x "$DESKTOP_DIR/fvault.desktop"

# Set as default handler for .vault files
xdg-mime default fvault.desktop application/x-fvault 2>/dev/null || true
update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true

echo
echo "=== Installation complete ==="
echo
echo "Usage:"
echo "  fvault                  # Launch the GUI"
echo "  fvault /path/to.vault   # Open a vault directly"
echo
echo "You can also double-click .vault files to open them."
