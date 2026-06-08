"""GTK TreeView-based file browser widget."""

import os
import shutil
import subprocess
import time

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GdkPixbuf, Gio, GLib, Pango


def _format_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _format_time(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


def _get_icon_for_path(path: str) -> Gio.Icon:
    if os.path.isdir(path):
        return Gio.ThemedIcon.new("folder")
    content_type, _ = Gio.content_type_guess(path, None)
    icon = Gio.content_type_get_icon(content_type)
    return icon


class FileBrowser(Gtk.Box):
    """File browser widget with toolbar, path bar, and tree view."""

    def __init__(self, root_path: str, on_modified=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.root_path = root_path
        self.current_path = root_path
        self.on_modified = on_modified  # callback when files change
        self._build_toolbar()
        self._build_path_bar()
        self._build_tree_view()
        self.refresh()

    def _build_toolbar(self):
        toolbar = Gtk.Toolbar()
        toolbar.set_style(Gtk.ToolbarStyle.BOTH_HORIZ)

        self.btn_up = Gtk.ToolButton(icon_name="go-up", label="Up")
        self.btn_up.set_tooltip_text("Go to parent folder")
        self.btn_up.connect("clicked", self._on_up)
        toolbar.add(self.btn_up)

        toolbar.add(Gtk.SeparatorToolItem())

        btn_add = Gtk.ToolButton(icon_name="list-add", label="Add Files")
        btn_add.set_is_important(True)
        btn_add.set_tooltip_text("Add files to vault")
        btn_add.connect("clicked", self._on_add_files)
        toolbar.add(btn_add)

        btn_add_folder = Gtk.ToolButton(icon_name="folder-new", label="New Folder")
        btn_add_folder.set_tooltip_text("Create new folder")
        btn_add_folder.connect("clicked", self._on_new_folder)
        toolbar.add(btn_add_folder)

        btn_rename = Gtk.ToolButton(icon_name="document-edit", label="Rename")
        btn_rename.set_tooltip_text("Rename selected item")
        btn_rename.connect("clicked", self._on_rename)
        toolbar.add(btn_rename)

        btn_delete = Gtk.ToolButton(icon_name="edit-delete", label="Delete")
        btn_delete.set_tooltip_text("Delete selected items")
        btn_delete.connect("clicked", self._on_delete)
        toolbar.add(btn_delete)

        toolbar.add(Gtk.SeparatorToolItem())

        btn_extract = Gtk.ToolButton(icon_name="document-save-as", label="Extract All")
        btn_extract.set_is_important(True)
        btn_extract.set_tooltip_text("Extract entire vault to a folder")
        btn_extract.connect("clicked", self._on_extract)
        toolbar.add(btn_extract)

        self.pack_start(toolbar, False, False, 0)

    def _build_path_bar(self):
        self.path_bar = Gtk.Box(spacing=4)
        self.path_bar.set_margin_start(8)
        self.path_bar.set_margin_end(8)
        self.path_bar.set_margin_top(4)
        self.path_bar.set_margin_bottom(4)
        self.pack_start(self.path_bar, False, False, 0)

    def _update_path_bar(self):
        for child in self.path_bar.get_children():
            self.path_bar.remove(child)

        rel = os.path.relpath(self.current_path, self.root_path)
        parts = [] if rel == "." else rel.split(os.sep)

        root_btn = Gtk.Button(label="Vault Root")
        root_btn.set_relief(Gtk.ReliefStyle.NONE)
        root_btn.connect("clicked", lambda _: self._navigate(self.root_path))
        self.path_bar.pack_start(root_btn, False, False, 0)

        accumulated = self.root_path
        for part in parts:
            sep = Gtk.Label(label="/")
            self.path_bar.pack_start(sep, False, False, 0)
            accumulated = os.path.join(accumulated, part)
            path_copy = accumulated
            btn = Gtk.Button(label=part)
            btn.set_relief(Gtk.ReliefStyle.NONE)
            btn.connect("clicked", lambda _, p=path_copy: self._navigate(p))
            self.path_bar.pack_start(btn, False, False, 0)

        self.path_bar.show_all()
        self.btn_up.set_sensitive(self.current_path != self.root_path)

    def _build_tree_view(self):
        # Columns: icon (Gio.Icon), name (str), size (str), modified (str), full_path (str), is_dir (bool), raw_size (int)
        self.store = Gtk.ListStore(Gio.Icon, str, str, str, str, bool, int)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        self.tree = Gtk.TreeView(model=self.store)
        self.tree.set_headers_visible(True)
        self.tree.set_enable_search(True)
        self.tree.set_search_column(1)
        self.tree.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)

        # Icon + Name column
        col_name = Gtk.TreeViewColumn("Name")
        col_name.set_expand(True)
        col_name.set_sort_column_id(1)

        icon_renderer = Gtk.CellRendererPixbuf()
        col_name.pack_start(icon_renderer, False)
        col_name.add_attribute(icon_renderer, "gicon", 0)

        name_renderer = Gtk.CellRendererText()
        name_renderer.set_property("ellipsize", Pango.EllipsizeMode.END)
        col_name.pack_start(name_renderer, True)
        col_name.add_attribute(name_renderer, "text", 1)

        self.tree.append_column(col_name)

        # Size column
        col_size = Gtk.TreeViewColumn("Size", Gtk.CellRendererText(), text=2)
        col_size.set_sort_column_id(6)
        col_size.set_min_width(80)
        self.tree.append_column(col_size)

        # Modified column
        col_mod = Gtk.TreeViewColumn("Modified", Gtk.CellRendererText(), text=3)
        col_mod.set_sort_column_id(3)
        col_mod.set_min_width(140)
        self.tree.append_column(col_mod)

        self.tree.connect("row-activated", self._on_row_activated)
        self.tree.connect("key-press-event", self._on_key_press)

        # Drag and drop - accept files from file manager
        self.tree.drag_dest_set(
            Gtk.DestDefaults.ALL,
            [Gtk.TargetEntry.new("text/uri-list", 0, 0)],
            Gdk.DragAction.COPY,
        )
        self.tree.connect("drag-data-received", self._on_drag_data_received)

        scroll.add(self.tree)
        self.pack_start(scroll, True, True, 0)

    def refresh(self):
        self.store.clear()
        try:
            entries = sorted(os.listdir(self.current_path))
        except OSError:
            return

        # Directories first, then files
        dirs = []
        files = []
        for name in entries:
            full = os.path.join(self.current_path, name)
            try:
                stat = os.stat(full)
            except OSError:
                continue
            is_dir = os.path.isdir(full)
            icon = _get_icon_for_path(full)
            size_str = "" if is_dir else _format_size(stat.st_size)
            mod_str = _format_time(stat.st_mtime)
            raw_size = 0 if is_dir else stat.st_size
            row = (icon, name, size_str, mod_str, full, is_dir, raw_size)
            if is_dir:
                dirs.append(row)
            else:
                files.append(row)

        for row in dirs + files:
            self.store.append(row)

        self._update_path_bar()

    def _navigate(self, path):
        self.current_path = path
        self.refresh()

    def _get_selected_paths(self) -> list[str]:
        sel = self.tree.get_selection()
        model, paths = sel.get_selected_rows()
        result = []
        for p in paths:
            it = model.get_iter(p)
            result.append(model.get_value(it, 4))  # full_path column
        return result

    def _notify_modified(self):
        if self.on_modified:
            self.on_modified()

    # --- Event handlers ---

    def _on_row_activated(self, tree, path, column):
        it = self.store.get_iter(path)
        full_path = self.store.get_value(it, 4)
        is_dir = self.store.get_value(it, 5)

        if is_dir:
            self._navigate(full_path)
        else:
            subprocess.Popen(["xdg-open", full_path])

    def _on_up(self, btn):
        if self.current_path != self.root_path:
            self._navigate(os.path.dirname(self.current_path))

    def _on_key_press(self, widget, event):
        if event.keyval == Gdk.KEY_Delete:
            self._on_delete(None)
            return True
        if event.keyval == Gdk.KEY_F2:
            self._on_rename(None)
            return True
        if event.keyval == Gdk.KEY_BackSpace:
            self._on_up(None)
            return True
        return False

    def _on_add_files(self, btn):
        dialog = Gtk.FileChooserDialog(
            title="Add Files to Vault",
            parent=self.get_toplevel(),
            action=Gtk.FileChooserAction.OPEN,
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_ADD, Gtk.ResponseType.OK,
        )
        dialog.set_select_multiple(True)

        # Add a button to switch to folder mode
        filter_box = Gtk.Box(spacing=8)
        add_folder_btn = Gtk.Button(label="Add Folder Instead...")
        filter_box.pack_start(add_folder_btn, False, False, 0)
        filter_box.show_all()
        dialog.set_extra_widget(filter_box)

        def switch_to_folder(_):
            dialog.destroy()
            self._add_folder()

        add_folder_btn.connect("clicked", switch_to_folder)

        if dialog.run() == Gtk.ResponseType.OK:
            for uri in dialog.get_filenames():
                dest = os.path.join(self.current_path, os.path.basename(uri))
                if os.path.isdir(uri):
                    shutil.copytree(uri, dest)
                else:
                    shutil.copy2(uri, dest)
            self.refresh()
            self._notify_modified()
        dialog.destroy()

    def _add_folder(self):
        dialog = Gtk.FileChooserDialog(
            title="Add Folder to Vault",
            parent=self.get_toplevel(),
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_ADD, Gtk.ResponseType.OK,
        )
        if dialog.run() == Gtk.ResponseType.OK:
            folder = dialog.get_filename()
            dest = os.path.join(self.current_path, os.path.basename(folder))
            shutil.copytree(folder, dest)
            self.refresh()
            self._notify_modified()
        dialog.destroy()

    def _on_new_folder(self, btn):
        dialog = Gtk.Dialog(
            title="New Folder",
            transient_for=self.get_toplevel(),
            modal=True,
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OK, Gtk.ResponseType.OK,
        )
        dialog.set_default_response(Gtk.ResponseType.OK)

        box = dialog.get_content_area()
        box.set_spacing(8)
        box.set_border_width(12)
        entry = Gtk.Entry()
        entry.set_placeholder_text("Folder name")
        entry.set_activates_default(True)
        box.pack_start(Gtk.Label(label="Folder name:", xalign=0), False, False, 0)
        box.pack_start(entry, False, False, 0)
        box.show_all()

        if dialog.run() == Gtk.ResponseType.OK:
            name = entry.get_text().strip()
            if name:
                path = os.path.join(self.current_path, name)
                os.makedirs(path, exist_ok=True)
                self.refresh()
                self._notify_modified()
        dialog.destroy()

    def _on_rename(self, btn):
        selected = self._get_selected_paths()
        if len(selected) != 1:
            return

        old_path = selected[0]
        old_name = os.path.basename(old_path)

        dialog = Gtk.Dialog(
            title="Rename",
            transient_for=self.get_toplevel(),
            modal=True,
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OK, Gtk.ResponseType.OK,
        )
        dialog.set_default_response(Gtk.ResponseType.OK)

        box = dialog.get_content_area()
        box.set_spacing(8)
        box.set_border_width(12)
        entry = Gtk.Entry()
        entry.set_text(old_name)
        entry.set_activates_default(True)
        entry.select_region(0, -1)
        box.pack_start(entry, False, False, 0)
        box.show_all()

        if dialog.run() == Gtk.ResponseType.OK:
            new_name = entry.get_text().strip()
            if new_name and new_name != old_name:
                new_path = os.path.join(os.path.dirname(old_path), new_name)
                os.rename(old_path, new_path)
                self.refresh()
                self._notify_modified()
        dialog.destroy()

    def _on_delete(self, btn):
        selected = self._get_selected_paths()
        if not selected:
            return

        names = [os.path.basename(p) for p in selected]
        msg = "\n".join(names)
        if len(names) > 5:
            msg = "\n".join(names[:5]) + f"\n... and {len(names) - 5} more"

        from dialogs import confirm_dialog
        if not confirm_dialog(
            self.get_toplevel(),
            f"Delete {len(selected)} item(s)?",
            msg,
        ):
            return

        for path in selected:
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
        self.refresh()
        self._notify_modified()

    def _on_extract(self, btn):
        dialog = Gtk.FileChooserDialog(
            title="Extract Vault To...",
            parent=self.get_toplevel(),
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            "Extract", Gtk.ResponseType.OK,
        )
        if dialog.run() == Gtk.ResponseType.OK:
            dest = dialog.get_filename()
            try:
                # Copy all contents from root, not just current dir
                for item in os.listdir(self.root_path):
                    src = os.path.join(self.root_path, item)
                    dst = os.path.join(dest, item)
                    if os.path.isdir(src):
                        shutil.copytree(src, dst)
                    else:
                        shutil.copy2(src, dst)
                from dialogs import error_dialog
                # Reuse error_dialog for info (it's just a message box)
                dlg = Gtk.MessageDialog(
                    transient_for=self.get_toplevel(), modal=True,
                    message_type=Gtk.MessageType.INFO,
                    buttons=Gtk.ButtonsType.OK,
                    text="Extraction complete",
                )
                dlg.format_secondary_text(f"Files extracted to:\n{dest}")
                dlg.run()
                dlg.destroy()
            except Exception as e:
                from dialogs import error_dialog
                error_dialog(self.get_toplevel(), "Extraction failed", str(e))
        dialog.destroy()

    def _on_drag_data_received(self, widget, context, x, y, data, info, timestamp):
        uris = data.get_uris()
        if not uris:
            return
        for uri in uris:
            if uri.startswith("file://"):
                path = GLib.filename_from_uri(uri)[0]
                dest = os.path.join(self.current_path, os.path.basename(path))
                if os.path.isdir(path):
                    shutil.copytree(path, dest)
                else:
                    shutil.copy2(path, dest)
        self.refresh()
        self._notify_modified()

    def count_all_files(self) -> int:
        count = 0
        for _, _, files in os.walk(self.root_path):
            count += len(files)
        return count
