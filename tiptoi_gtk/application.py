"""
Adw.Application-Subklasse für tiptoi-gtk.

Registriert die Anwendung mit der Application-ID 'io.github.tiptoi_linux.TiptoiManager'
und instanziiert beim ersten Activate-Signal das Hauptfenster.
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio

from tiptoi_gtk.window import TiptoiWindow

APP_ID = "io.github.tiptoi_linux.TiptoiManager"


class TiptoiApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )
        self.connect("activate", self._on_activate)

    def _on_activate(self, _app: "TiptoiApplication") -> None:
        win = self.props.active_window
        if not win:
            win = TiptoiWindow(application=self)
        win.present()
