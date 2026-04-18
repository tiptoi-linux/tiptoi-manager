"""Einstellungsfenster (Adw.PreferencesWindow)."""

import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk

from tiptoi_gtk import _
from tiptoi_gtk.backend import catalog
from tiptoi_gtk.backend import settings_manager as settings


class PreferencesDialogMixin:
    """Mixin für das Einstellungsfenster und dessen Callbacks."""

    def _show_preferences(self, _action=None, _param=None) -> None:
        prefs = Adw.PreferencesWindow(transient_for=self, modal=True)
        prefs.set_title(_("Einstellungen"))

        page = Adw.PreferencesPage(
            title=_("Allgemein"),
            icon_name="preferences-system-symbolic",
        )
        prefs.add(page)

        # ── Download-Ordner ───────────────────────────────────────────────────
        dl_group = Adw.PreferencesGroup(title=_("Speicherort"))
        page.add(dl_group)

        dl_entry_row = Adw.EntryRow(
            title=_("Download-Ordner"),
            text=str(settings.download_dir()),
        )
        dl_entry_row.connect("apply", self._on_dl_dir_entry_apply)
        dl_entry_row.connect("notify::text", lambda row, _: None)

        choose_btn = Gtk.Button(
            icon_name="folder-open-symbolic",
            tooltip_text=_("Ordner wählen"),
            valign=Gtk.Align.CENTER,
        )
        choose_btn.add_css_class("flat")
        choose_btn.connect("clicked", self._on_choose_download_dir, prefs, dl_entry_row)
        dl_entry_row.add_suffix(choose_btn)
        dl_group.add(dl_entry_row)

        # ── Produktliste ──────────────────────────────────────────────────────
        csv_group = Adw.PreferencesGroup(title=_("Produktliste"))
        page.add(csv_group)

        adjustment = Gtk.Adjustment(
            value=settings.get("csv_max_age_days"),
            lower=1, upper=365, step_increment=1, page_increment=7,
        )
        age_spin_row = Adw.SpinRow(
            title=_("Cache-Gültigkeit"),
            subtitle=_("Produktliste nach dieser Anzahl Tage neu laden"),
            adjustment=adjustment,
            digits=0,
        )
        age_spin_row.connect("notify::value", self._on_csv_age_changed)
        csv_group.add(age_spin_row)

        url_entry_row = Adw.EntryRow(
            title=_("Download-URL"),
            text=settings.get("csv_url"),
        )
        url_entry_row.connect("apply", self._on_csv_url_entry_apply)
        _default_url = "https://cdn.ravensburger.de/db/tiptoi.csv"
        reset_url_btn = Gtk.Button(
            icon_name="edit-undo-symbolic",
            tooltip_text=_("Auf Standard zurücksetzen"),
            valign=Gtk.Align.CENTER,
        )
        reset_url_btn.add_css_class("flat")
        reset_url_btn.connect(
            "clicked",
            lambda _: (
                url_entry_row.set_text(_default_url),
                settings.set_value("csv_url", _default_url),
            ),
        )
        url_entry_row.add_suffix(reset_url_btn)
        csv_group.add(url_entry_row)

        age = catalog.catalog_age_days()
        age_str = (
            _("{days:.0f} Tage alt").format(days=age)
            if age is not None else _("nicht vorhanden")
        )
        cache_status_row = Adw.ActionRow(
            title=_("Aktueller Cache"),
            subtitle=f"~/.cache/tiptoi-gtk/produkte.csv · {age_str}",
        )
        refresh_btn = Gtk.Button(label=_("Jetzt aktualisieren"), valign=Gtk.Align.CENTER)
        refresh_btn.add_css_class("flat")
        refresh_btn.connect("clicked", self._on_force_refresh_catalog, prefs)
        cache_status_row.add_suffix(refresh_btn)
        csv_group.add(cache_status_row)

        prefs.present()

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def _on_dl_dir_entry_apply(self, row: Adw.EntryRow) -> None:
        new_path = Path(row.get_text().strip())
        settings.set_download_dir(new_path)
        self._refresh_downloads_page()
        self._show_toast(_("Download-Ordner: {path}").format(path=new_path))

    def _on_csv_age_changed(self, spin_row: Adw.SpinRow, _param) -> None:
        settings.set_value("csv_max_age_days", int(spin_row.get_value()))

    def _on_csv_url_entry_apply(self, row: Adw.EntryRow) -> None:
        url = row.get_text().strip()
        if url:
            settings.set_value("csv_url", url)
            self._show_toast(
                _("URL gespeichert. Beim nächsten Aktualisieren wird sie verwendet.")
            )

    def _on_choose_download_dir(
        self, _btn: Gtk.Button, parent: Gtk.Window, entry_row: Adw.EntryRow
    ) -> None:
        dialog = Gtk.FileDialog(title=_("Download-Ordner wählen"))
        dialog.set_initial_folder(Gio.File.new_for_path(str(settings.download_dir())))
        dialog.select_folder(
            parent, None,
            lambda d, r: self._on_download_dir_chosen(d, r, entry_row),
        )

    def _on_download_dir_chosen(
        self, dialog: Gtk.FileDialog, result: Gio.AsyncResult, entry_row: Adw.EntryRow
    ) -> None:
        try:
            folder = dialog.select_folder_finish(result)
            if folder:
                new_path = Path(folder.get_path())
                settings.set_download_dir(new_path)
                entry_row.set_text(str(new_path))
                self._refresh_downloads_page()
                self._show_toast(_("Download-Ordner: {path}").format(path=new_path))
        except GLib.Error:
            pass

    def _on_force_refresh_catalog(
        self, _btn: Gtk.Button, prefs: Adw.PreferencesWindow
    ) -> None:
        prefs.close()
        self._show_toast(_("Produktliste wird aktualisiert…"))
        self._products = []
        self._available_years = []
        self._loading_label.set_visible(True)
        self._search_results_list.set_visible(False)

        while self._year_model.get_n_items() > 1:
            self._year_model.remove(self._year_model.get_n_items() - 1)
        self._year_dropdown.set_selected(0)
        self._selected_year = None

        def worker() -> None:
            products, error = catalog.fetch_and_load(force=True)
            GLib.idle_add(self._on_catalog_loaded, products, error)

        threading.Thread(target=worker, daemon=True).start()
