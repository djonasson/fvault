"""GTK dialogs for password entry and confirmations."""

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk


class PasswordDialog(Gtk.Dialog):
    """Password entry dialog with optional confirmation field."""

    def __init__(self, parent, title="Enter Password", confirm=False):
        super().__init__(title=title, transient_for=parent, modal=True)
        self.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OK, Gtk.ResponseType.OK,
        )
        self.set_default_response(Gtk.ResponseType.OK)
        self.set_default_size(350, -1)
        self.set_border_width(12)

        box = self.get_content_area()
        box.set_spacing(8)

        self.password_entry = Gtk.Entry()
        self.password_entry.set_visibility(False)
        self.password_entry.set_placeholder_text("Password")
        self.password_entry.set_activates_default(True)
        box.pack_start(Gtk.Label(label="Password:", xalign=0), False, False, 0)
        box.pack_start(self.password_entry, False, False, 0)

        self.confirm_entry = None
        if confirm:
            self.confirm_entry = Gtk.Entry()
            self.confirm_entry.set_visibility(False)
            self.confirm_entry.set_placeholder_text("Confirm password")
            self.confirm_entry.set_activates_default(True)
            box.pack_start(Gtk.Label(label="Confirm:", xalign=0), False, False, 0)
            box.pack_start(self.confirm_entry, False, False, 0)

        show_check = Gtk.CheckButton(label="Show password")
        show_check.connect("toggled", self._on_show_toggled)
        box.pack_start(show_check, False, False, 4)

        self.error_label = Gtk.Label()
        self.error_label.set_markup("")
        box.pack_start(self.error_label, False, False, 0)

        box.show_all()
        self.error_label.hide()

    def _on_show_toggled(self, btn):
        visible = btn.get_active()
        self.password_entry.set_visibility(visible)
        if self.confirm_entry:
            self.confirm_entry.set_visibility(visible)

    def get_password(self) -> str | None:
        """Run dialog and return password, or None if cancelled."""
        while True:
            response = self.run()
            if response != Gtk.ResponseType.OK:
                self.destroy()
                return None

            pw = self.password_entry.get_text()
            if not pw:
                self._show_error("Password cannot be empty")
                continue

            if self.confirm_entry:
                if pw != self.confirm_entry.get_text():
                    self._show_error("Passwords do not match")
                    self.confirm_entry.set_text("")
                    continue

            self.destroy()
            return pw

    def _show_error(self, msg):
        self.error_label.set_markup(f'<span color="red">{msg}</span>')
        self.error_label.show()


def confirm_dialog(parent, title, message) -> bool:
    dlg = Gtk.MessageDialog(
        transient_for=parent, modal=True,
        message_type=Gtk.MessageType.QUESTION,
        buttons=Gtk.ButtonsType.YES_NO,
        text=title,
    )
    dlg.format_secondary_text(message)
    response = dlg.run()
    dlg.destroy()
    return response == Gtk.ResponseType.YES


def save_changes_dialog(parent) -> str:
    """Ask to save changes. Returns 'save', 'discard', or 'cancel'."""
    dlg = Gtk.MessageDialog(
        transient_for=parent, modal=True,
        message_type=Gtk.MessageType.WARNING,
        text="Save changes?",
    )
    dlg.format_secondary_text("The vault has been modified. Save before closing?")
    dlg.add_buttons(
        "Discard", Gtk.ResponseType.REJECT,
        Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
        Gtk.STOCK_SAVE, Gtk.ResponseType.ACCEPT,
    )
    dlg.set_default_response(Gtk.ResponseType.ACCEPT)
    response = dlg.run()
    dlg.destroy()
    if response == Gtk.ResponseType.ACCEPT:
        return "save"
    elif response == Gtk.ResponseType.REJECT:
        return "discard"
    return "cancel"


def error_dialog(parent, title, message):
    dlg = Gtk.MessageDialog(
        transient_for=parent, modal=True,
        message_type=Gtk.MessageType.ERROR,
        buttons=Gtk.ButtonsType.OK,
        text=title,
    )
    dlg.format_secondary_text(message)
    dlg.run()
    dlg.destroy()
