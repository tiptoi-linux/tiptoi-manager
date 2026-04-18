"""Stift-Tab: Verbindungsstatus, Stift-Infos und installierte Produkte."""

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk

from tiptoi_gtk import _
from tiptoi_gtk.backend import gme
from tiptoi_gtk.backend.pen import PenMonitor


class PenViewMixin:
    """Mixin für den Stift-Tab und den PenMonitor."""

    # ── Aufbau ────────────────────────────────────────────────────────────────

    def _build_pen_view(self) -> None:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._view_stack.add_titled_with_icon(
            outer, "pen", _("Stift"), "media-removable-symbolic"
        )

        self._pen_page_stack = Gtk.Stack(vexpand=True)
        outer.append(self._pen_page_stack)

        not_connected = Adw.StatusPage(
            icon_name="media-removable-symbolic",
            title=_("Kein Stift verbunden"),
            description=_("Schließe deinen TipToi-Stift über USB an."),
            vexpand=True,
        )
        self._pen_page_stack.add_named(not_connected, "disconnected")

        connected_scroll = Gtk.ScrolledWindow(vexpand=True)
        self._pen_page_stack.add_named(connected_scroll, "connected")

        clamp = Adw.Clamp(maximum_size=800, margin_top=18, margin_bottom=18)
        connected_scroll.set_child(clamp)

        self._pen_content_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            margin_start=12, margin_end=12, spacing=18,
        )
        clamp.set_child(self._pen_content_box)

        info_group = Adw.PreferencesGroup(title=_("Stift-Informationen"))
        self._pen_content_box.append(info_group)

        self._pen_path_row = Adw.ActionRow(title=_("Pfad"), subtitle="–")
        info_group.add(self._pen_path_row)

        self._pen_storage_row = Adw.ActionRow(title=_("Speicher"), subtitle="–")
        info_group.add(self._pen_storage_row)

        self._pen_files_group = Adw.PreferencesGroup(title=_("Installierte Produkte"))
        self._pen_content_box.append(self._pen_files_group)

        self._pen_page_stack.set_visible_child_name("disconnected")

    # ── PenMonitor ────────────────────────────────────────────────────────────

    def _setup_pen_monitor(self) -> None:
        self._pen_monitor = PenMonitor(
            on_connected=self._on_pen_connected,
            on_disconnected=self._on_pen_disconnected,
        )
        existing = self._pen_monitor.scan_existing_mounts()
        if existing:
            label, path = existing
            self._on_pen_connected(label, path)

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def _on_pen_connected(self, label: str, path: str) -> None:
        self._pen_path = path
        self._pen_label = label
        self._pen_banner.set_title(
            _("Stift verbunden: {label} ({path})").format(label=label, path=path)
        )
        self._pen_banner.set_revealed(True)
        self._update_pen_view()
        self._update_search_results()

    def _on_pen_disconnected(self, _label: str, _path: str) -> None:
        self._pen_path = None
        self._pen_label = ""
        self._pen_banner.set_revealed(False)
        self._pen_page_stack.set_visible_child_name("disconnected")
        self._show_toast(_("Stift getrennt."))
        self._update_search_results()

    def _on_pen_banner_clicked(self, _banner: Adw.Banner) -> None:
        self._view_stack.set_visible_child_name("pen")

    def _on_delete_from_pen_clicked(self, _btn: Gtk.Button, gme_path: Path) -> None:
        dialog = Adw.AlertDialog(
            heading=_("Datei löschen?"),
            body=_("\u201e{name}\u201c wird dauerhaft vom Stift entfernt.").format(
                name=gme_path.name
            ),
        )
        dialog.add_response("cancel", _("Abbrechen"))
        dialog.add_response("delete", _("Löschen"))
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_delete_confirmed, gme_path)
        dialog.present(self)

    def _on_delete_confirmed(
        self, _dialog: Adw.AlertDialog, response: str, gme_path: Path
    ) -> None:
        if response != "delete":
            return
        error = gme.delete_from_pen(gme_path)
        if error:
            self._show_toast(_("Fehler beim Löschen: {error}").format(error=error))
        else:
            self._show_toast(_("{name} gelöscht.").format(name=gme_path.name))
            self._update_pen_view()

    # ── View-Aktualisierung ───────────────────────────────────────────────────

    def _update_pen_view(self) -> None:
        if not self._pen_path:
            self._pen_page_stack.set_visible_child_name("disconnected")
            return

        self._pen_page_stack.set_visible_child_name("connected")

        label_str = (
            f"{self._pen_label} ({self._pen_path})"
            if self._pen_label else self._pen_path
        )
        self._pen_path_row.set_subtitle(label_str)

        free, total = gme.pen_disk_info(self._pen_path)
        if total > 0:
            self._pen_storage_row.set_subtitle(
                _("{free} frei von {total}").format(
                    free=gme.format_size(free), total=gme.format_size(total)
                )
            )

        # Alte Datei-Zeilen entfernen
        for row, _ in self._pen_file_rows:
            self._pen_files_group.remove(row)
        self._pen_file_rows.clear()

        files = gme.list_gme_files(self._pen_path)

        if not files:
            row = Adw.ActionRow(title=_("Keine Produkte installiert"))
            row.set_sensitive(False)
            self._pen_files_group.add(row)
            self._pen_file_rows.append((row, Path()))
            return

        for f in files:
            product_name = self._find_product_name(f.stem) or f.stem
            row = Adw.ActionRow(
                title=product_name,
                subtitle=gme.format_size(f.stat().st_size),
            )

            delete_btn = Gtk.Button(
                icon_name="user-trash-symbolic",
                tooltip_text=_("Vom Stift löschen"),
                valign=Gtk.Align.CENTER,
            )
            delete_btn.add_css_class("flat")
            delete_btn.add_css_class("error")
            delete_btn.connect("clicked", self._on_delete_from_pen_clicked, f)
            row.add_suffix(delete_btn)

            self._pen_files_group.add(row)
            self._pen_file_rows.append((row, f))
