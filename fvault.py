#!/usr/bin/env python3
"""fvault - Encrypted Folder Vault GUI application."""

import atexit
import os
import signal
import shutil
import sys
import threading

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib, Gio

import config
import crypto
import vault
from dialogs import (
    PasswordDialog, confirm_dialog, save_changes_dialog, error_dialog,
)
from filebrowser import FileBrowser


class FVaultWindow(Gtk.ApplicationWindow):

    def __init__(self, app):
        super().__init__(application=app, title="fvault")
        self.set_default_size(900, 600)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.connect("delete-event", self._on_window_close)

        # State
        self.vault_path = None      # path to the .vault file
        self.temp_dir = None        # temp dir with decrypted contents
        self.password = None        # cached password for save
        self.modified = False       # whether vault contents changed
        self.browser = None         # FileBrowser widget

        # Main stack for switching between home and browser views
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.add(self.stack)

        self._build_home_view()
        self.stack.set_visible_child_name("home")

    def _build_home_view(self):
        home = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Header area
        header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        header.set_margin_top(60)
        header.set_margin_bottom(20)
        header.set_halign(Gtk.Align.CENTER)

        # App icon
        icon = Gtk.Image.new_from_icon_name("security-high", Gtk.IconSize.DIALOG)
        icon.set_pixel_size(64)
        header.pack_start(icon, False, False, 0)

        title = Gtk.Label()
        title.set_markup('<span size="xx-large" weight="bold">fvault</span>')
        header.pack_start(title, False, False, 0)

        subtitle = Gtk.Label(label="Encrypted Folder Vault")
        subtitle.get_style_context().add_class("dim-label")
        header.pack_start(subtitle, False, False, 0)

        home.pack_start(header, False, False, 0)

        # Buttons
        btn_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        btn_box.set_halign(Gtk.Align.CENTER)
        btn_box.set_margin_top(20)

        btn_create = Gtk.Button(label="Create New Vault")
        btn_create.set_size_request(280, 44)
        btn_create.get_style_context().add_class("suggested-action")
        btn_create.connect("clicked", self._on_create_vault)
        btn_box.pack_start(btn_create, False, False, 0)

        btn_open = Gtk.Button(label="Open Existing Vault")
        btn_open.set_size_request(280, 44)
        btn_open.connect("clicked", self._on_open_vault)
        btn_box.pack_start(btn_open, False, False, 0)

        home.pack_start(btn_box, False, False, 0)

        # Recent vaults
        recent_frame = Gtk.Frame(label="Recent Vaults")
        recent_frame.set_margin_top(30)
        recent_frame.set_margin_start(80)
        recent_frame.set_margin_end(80)
        recent_frame.set_margin_bottom(20)

        self.recent_list = Gtk.ListBox()
        self.recent_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.recent_list.set_activate_on_single_click(True)
        self.recent_list.connect("row-activated", self._on_recent_activated)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(120)
        scroll.add(self.recent_list)
        recent_frame.add(scroll)
        home.pack_start(recent_frame, True, True, 0)

        self.stack.add_named(home, "home")
        self._refresh_recent()

    def _refresh_recent(self):
        for child in self.recent_list.get_children():
            self.recent_list.remove(child)

        recents = config.get_recent_vaults()
        if not recents:
            row = Gtk.ListBoxRow()
            label = Gtk.Label(label="No recent vaults")
            label.get_style_context().add_class("dim-label")
            label.set_margin_top(12)
            label.set_margin_bottom(12)
            row.add(label)
            row.set_activatable(False)
            self.recent_list.add(row)
        else:
            for path in recents:
                row = Gtk.ListBoxRow()
                box = Gtk.Box(spacing=12)
                box.set_margin_top(6)
                box.set_margin_bottom(6)
                box.set_margin_start(12)
                box.set_margin_end(12)

                icon = Gtk.Image.new_from_icon_name("folder-locked", Gtk.IconSize.LARGE_TOOLBAR)
                box.pack_start(icon, False, False, 0)

                vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
                name_label = Gtk.Label(xalign=0)
                name_label.set_markup(f"<b>{GLib.markup_escape_text(os.path.basename(path))}</b>")
                vbox.pack_start(name_label, False, False, 0)

                path_label = Gtk.Label(label=path, xalign=0)
                path_label.get_style_context().add_class("dim-label")
                path_label.set_ellipsize(2)  # PANGO_ELLIPSIZE_END
                vbox.pack_start(path_label, False, False, 0)

                box.pack_start(vbox, True, True, 0)

                exists = os.path.exists(path)
                if not exists:
                    missing = Gtk.Label(label="(missing)")
                    missing.get_style_context().add_class("dim-label")
                    box.pack_end(missing, False, False, 0)

                del_btn = Gtk.Button.new_from_icon_name("edit-delete", Gtk.IconSize.BUTTON)
                del_btn.set_tooltip_text("Delete this vault")
                del_btn.set_relief(Gtk.ReliefStyle.NONE)
                del_btn.connect("clicked", self._on_delete_recent, path)
                box.pack_end(del_btn, False, False, 0)

                row.add(box)
                row.vault_path = path
                row.set_activatable(exists)
                self.recent_list.add(row)

        self.recent_list.show_all()

    def _build_browser_view(self):
        browser_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        # Header bar for browser mode
        hbar = Gtk.Box(spacing=8)
        hbar.set_margin_start(8)
        hbar.set_margin_end(8)
        hbar.set_margin_top(6)
        hbar.set_margin_bottom(6)

        vault_icon = Gtk.Image.new_from_icon_name("security-high", Gtk.IconSize.BUTTON)
        hbar.pack_start(vault_icon, False, False, 0)

        self.vault_label = Gtk.Label()
        self.vault_label.set_markup(
            f"<b>{GLib.markup_escape_text(os.path.basename(self.vault_path))}</b>"
        )
        hbar.pack_start(self.vault_label, False, False, 0)

        self.modified_indicator = Gtk.Label()
        hbar.pack_start(self.modified_indicator, False, False, 0)

        # Right side buttons
        btn_save = Gtk.Button(label="Save")
        btn_save.get_style_context().add_class("suggested-action")
        btn_save.set_tooltip_text("Save vault (re-encrypt)")
        btn_save.connect("clicked", self._on_save)
        hbar.pack_end(btn_save, False, False, 0)

        btn_lock = Gtk.Button(label="Lock & Close")
        btn_lock.set_tooltip_text("Save and close vault")
        btn_lock.connect("clicked", self._on_lock)
        hbar.pack_end(btn_lock, False, False, 0)

        browser_box.pack_start(hbar, False, False, 0)
        browser_box.pack_start(Gtk.Separator(), False, False, 0)

        # File browser
        self.browser = FileBrowser(self.temp_dir, on_modified=self._mark_modified)
        browser_box.pack_start(self.browser, True, True, 0)

        # Status bar
        self.status_bar = Gtk.Statusbar()
        browser_box.pack_start(self.status_bar, False, False, 0)
        self._update_status()

        # Remove old browser view if exists
        old = self.stack.get_child_by_name("browser")
        if old:
            self.stack.remove(old)

        self.stack.add_named(browser_box, "browser")
        browser_box.show_all()

    def _update_status(self):
        if self.browser:
            count = self.browser.count_all_files()
            self.status_bar.push(0, f"  Vault unlocked  |  {count} file(s)")

    def _mark_modified(self):
        self.modified = True
        self.modified_indicator.set_markup('  <span color="orange">(modified)</span>')

    def _clear_modified(self):
        self.modified = False
        self.modified_indicator.set_text("")

    # --- Vault operations ---

    def _delete_vault_file(self, vault_path):
        """Delete a vault file with double confirmation."""
        name = os.path.basename(vault_path)
        if not confirm_dialog(
            self,
            f"Delete {name}?",
            f"This will permanently delete the encrypted vault file:\n\n"
            f"{vault_path}\n\n"
            f"This cannot be undone.",
        ):
            return
        # Second confirmation — type the vault name
        dlg = Gtk.Dialog(
            title="Confirm deletion",
            transient_for=self, modal=True,
        )
        dlg.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            "Delete", Gtk.ResponseType.OK,
        )
        dlg.set_default_response(Gtk.ResponseType.OK)
        ok_btn = dlg.get_widget_for_response(Gtk.ResponseType.OK)
        ok_btn.get_style_context().add_class("destructive-action")
        ok_btn.set_sensitive(False)

        box = dlg.get_content_area()
        box.set_spacing(8)
        box.set_border_width(12)
        box.pack_start(
            Gtk.Label(label=f"Type \"{name}\" to confirm:", xalign=0),
            False, False, 0,
        )
        entry = Gtk.Entry()
        entry.set_activates_default(True)

        def on_changed(e):
            ok_btn.set_sensitive(e.get_text().strip() == name)

        entry.connect("changed", on_changed)
        box.pack_start(entry, False, False, 0)
        box.show_all()

        if dlg.run() == Gtk.ResponseType.OK:
            dlg.destroy()
            try:
                os.remove(vault_path)
            except OSError as e:
                error_dialog(self, "Deletion failed", str(e))
                return
            config.remove_recent_vault(vault_path)
            self._refresh_recent()
        else:
            dlg.destroy()

    def _on_delete_recent(self, btn, vault_path):
        """Delete a vault from the recent list row's delete button."""
        if not os.path.exists(vault_path):
            config.remove_recent_vault(vault_path)
            self._refresh_recent()
            return
        self._delete_vault_file(vault_path)

    def _on_create_vault(self, btn):
        dialog = Gtk.FileChooserDialog(
            title="Select Folder to Encrypt",
            parent=self,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            "Encrypt", Gtk.ResponseType.OK,
        )
        if dialog.run() != Gtk.ResponseType.OK:
            dialog.destroy()
            return

        folder_path = dialog.get_filename()
        dialog.destroy()

        # Choose save location
        save_dialog = Gtk.FileChooserDialog(
            title="Save Vault As",
            parent=self,
            action=Gtk.FileChooserAction.SAVE,
        )
        save_dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_SAVE, Gtk.ResponseType.OK,
        )
        save_dialog.set_do_overwrite_confirmation(True)
        parent_dir = os.path.dirname(folder_path)
        if parent_dir:
            save_dialog.set_current_folder(parent_dir)
        save_dialog.set_current_name(os.path.basename(folder_path) + ".vault")

        vault_filter = Gtk.FileFilter()
        vault_filter.set_name("Vault files")
        vault_filter.add_pattern("*.vault")
        save_dialog.add_filter(vault_filter)

        if save_dialog.run() != Gtk.ResponseType.OK:
            save_dialog.destroy()
            return

        vault_path = save_dialog.get_filename()
        if not vault_path.endswith(".vault"):
            vault_path += ".vault"
        save_dialog.destroy()

        # Get password
        pw_dialog = PasswordDialog(self, "Set Vault Password", confirm=True)
        password = pw_dialog.get_password()
        if password is None:
            return

        # Create vault with progress
        self._run_with_spinner("Encrypting...", lambda: vault.create_vault(
            folder_path, vault_path, password
        ), lambda: self._on_create_done(vault_path, folder_path))

    def _on_create_done(self, vault_path, folder_path):
        config.add_recent_vault(vault_path)
        self._refresh_recent()

        if confirm_dialog(
            self,
            "Vault created successfully",
            f"Delete the original folder?\n\n{folder_path}",
        ):
            shutil.rmtree(folder_path)

        if confirm_dialog(self, "Open vault?", "Would you like to open the vault now?"):
            self._do_open_vault(vault_path)

    def _on_open_vault(self, btn):
        dialog = Gtk.FileChooserDialog(
            title="Open Vault",
            parent=self,
            action=Gtk.FileChooserAction.OPEN,
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OPEN, Gtk.ResponseType.OK,
        )
        vault_filter = Gtk.FileFilter()
        vault_filter.set_name("Vault files (*.vault)")
        vault_filter.add_pattern("*.vault")
        dialog.add_filter(vault_filter)

        all_filter = Gtk.FileFilter()
        all_filter.set_name("All files")
        all_filter.add_pattern("*")
        dialog.add_filter(all_filter)

        if dialog.run() == Gtk.ResponseType.OK:
            path = dialog.get_filename()
            dialog.destroy()
            self._do_open_vault(path)
        else:
            dialog.destroy()

    def _on_recent_activated(self, listbox, row):
        if hasattr(row, "vault_path"):
            self._do_open_vault(row.vault_path)

    def _do_open_vault(self, vault_path, attempts=0):
        if not os.path.exists(vault_path):
            error_dialog(self, "File not found", f"Vault not found:\n{vault_path}")
            config.remove_recent_vault(vault_path)
            self._refresh_recent()
            return

        pw_dialog = PasswordDialog(self, f"Unlock {os.path.basename(vault_path)}")
        password = pw_dialog.get_password()
        if password is None:
            return

        def do_decrypt():
            return vault.open_vault(vault_path, password)

        def on_success(temp_dir):
            self.vault_path = vault_path
            self.temp_dir = temp_dir
            self.password = password
            self.modified = False
            config.add_recent_vault(vault_path)

            self._build_browser_view()
            self.stack.set_visible_child_name("browser")
            self._clear_modified()
            self.set_title(f"fvault - {os.path.basename(vault_path)}")

        def on_error(e):
            if "InvalidTag" in str(type(e).__name__) or "InvalidTag" in str(e):
                attempts_left = 2 - attempts
                if attempts_left > 0:
                    error_dialog(self, "Wrong password",
                                 f"Incorrect password. {attempts_left} attempt(s) remaining.")
                    self._do_open_vault(vault_path, attempts + 1)
                else:
                    error_dialog(self, "Wrong password", "Too many failed attempts.")
            else:
                error_dialog(self, "Error opening vault", str(e))

        self._run_with_spinner("Decrypting...", do_decrypt, on_success, on_error)

    def _on_save(self, btn=None):
        if not self.vault_path or not self.temp_dir:
            return

        def do_save():
            vault.save_vault(self.temp_dir, self.vault_path, self.password)

        def on_done(_=None):
            self._clear_modified()
            self._update_status()

        self._run_with_spinner("Saving...", do_save, on_done)

    def _on_lock(self, btn=None):
        if self.modified:
            choice = save_changes_dialog(self)
            if choice == "cancel":
                return
            elif choice == "save":
                vault.save_vault(self.temp_dir, self.vault_path, self.password)

        self._cleanup_temp()
        self.vault_path = None
        self.password = None
        self.modified = False
        self.browser = None
        self.stack.set_visible_child_name("home")
        self.set_title("fvault")
        self._refresh_recent()

    def _on_window_close(self, widget, event):
        if self.vault_path and self.temp_dir:
            if self.modified:
                choice = save_changes_dialog(self)
                if choice == "cancel":
                    return True  # prevent close
                elif choice == "save":
                    vault.save_vault(self.temp_dir, self.vault_path, self.password)
            self._cleanup_temp()
        return False  # allow close

    def _cleanup_temp(self):
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
            vault._active_temp_dirs.discard(self.temp_dir)
            self.temp_dir = None

    def _run_with_spinner(self, message, task_fn, on_success=None, on_error=None):
        """Run a task in a thread with a spinner overlay."""
        # Simple spinner dialog
        spinner_dialog = Gtk.Dialog(
            title="", transient_for=self, modal=True,
        )
        spinner_dialog.set_decorated(False)
        spinner_dialog.set_default_size(200, 80)
        box = spinner_dialog.get_content_area()
        box.set_spacing(12)
        box.set_margin_top(20)
        box.set_margin_bottom(20)
        box.set_margin_start(20)
        box.set_margin_end(20)

        spinner = Gtk.Spinner()
        spinner.start()
        box.pack_start(spinner, False, False, 0)
        box.pack_start(Gtk.Label(label=message), False, False, 0)
        box.show_all()
        spinner_dialog.show()

        def worker():
            try:
                result = task_fn()
                GLib.idle_add(lambda: _finish(result, None))
            except Exception as e:
                GLib.idle_add(lambda: _finish(None, e))

        def _finish(result, error):
            spinner_dialog.destroy()
            if error:
                if on_error:
                    on_error(error)
                else:
                    error_dialog(self, "Error", str(error))
            elif on_success:
                on_success(result) if result is not None else on_success()
            return False

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()


class FVaultApp(Gtk.Application):

    def __init__(self):
        super().__init__(
            application_id="com.fvault.app",
            flags=Gio.ApplicationFlags.HANDLES_OPEN,
        )

    def do_activate(self):
        win = FVaultWindow(self)
        win.show_all()

    def do_open(self, files, n_files, hint):
        self.do_activate()
        win = self.get_active_window()
        if files:
            win._do_open_vault(files[0].get_path())


def _signal_cleanup(signum, frame):
    """Signal handler: wipe temp dirs then re-raise for default behavior."""
    vault.cleanup_active_temp_dirs()
    # Re-raise with default handler so the exit code reflects the signal
    signal.signal(signum, signal.SIG_DFL)
    os.kill(os.getpid(), signum)


def main():
    # Add the script's directory to sys.path so imports work
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)

    # Clean up stale temp dirs from previous crashed sessions
    vault.cleanup_stale_temp_dirs()

    # Register cleanup for crashes / unexpected exits
    atexit.register(vault.cleanup_active_temp_dirs)
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, _signal_cleanup)

    app = FVaultApp()
    app.run(sys.argv)


if __name__ == "__main__":
    main()
