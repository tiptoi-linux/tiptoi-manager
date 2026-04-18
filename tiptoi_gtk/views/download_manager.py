"""Aktive-Downloads-Panel und Download-Steuerung."""

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Pango

from tiptoi_gtk import _
from tiptoi_gtk.backend import gme
from tiptoi_gtk.backend.downloader import CANCEL_SENTINEL, download_gme
from tiptoi_gtk.model.product import Product


class DownloadManagerMixin:
    """Mixin für parallele Downloads und das Aktiv-Downloads-Panel."""

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def _on_download_clicked(self, _btn: Gtk.Button, product: Product) -> None:
        self._start_download(product, copy_to_pen_after=False)

    def _on_download_to_pen_clicked(self, _btn: Gtk.Button, product: Product) -> None:
        self._start_download(product, copy_to_pen_after=True)

    def _on_cancel_download_clicked(self, _btn: Gtk.Button, artikelnummer: str) -> None:
        if artikelnummer in self._active_downloads:
            self._active_downloads[artikelnummer]["event"].set()

    # ── Download starten ──────────────────────────────────────────────────────

    def _start_download(self, product: Product, copy_to_pen_after: bool) -> None:
        art = product.artikelnummer
        if art in self._active_downloads:
            self._show_toast(_("Dieser Download läuft bereits."))
            return

        dest = self._dest_path(product)

        row, progress_bar, size_lbl = self._make_active_dl_row(product)
        self._active_dl_list.append(row)
        self._active_dl_revealer.set_reveal_child(True)

        def size_cb(size: int) -> None:
            if size > 0:
                size_lbl.set_label(gme.format_size(size))

        def progress_cb(fraction: float) -> None:
            progress_bar.set_fraction(fraction)

        def done_cb(ok: bool, result: str) -> None:
            self._on_download_done(art, ok, result, copy_to_pen_after)

        cancel_event = download_gme(
            url=product.download_url,
            dest=dest,
            progress_cb=progress_cb,
            done_cb=done_cb,
            size_cb=size_cb,
        )

        self._active_downloads[art] = {
            "event": cancel_event,
            "row": row,
            "progress": progress_bar,
            "size_lbl": size_lbl,
        }

    def _make_active_dl_row(
        self, product: Product
    ) -> tuple[Gtk.ListBoxRow, Gtk.ProgressBar, Gtk.Label]:
        """Erstellt eine Download-Zeile für das Aktiv-Panel."""
        row = Gtk.ListBoxRow(selectable=False)

        outer = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            margin_start=12, margin_end=12,
            margin_top=10, margin_bottom=10,
            spacing=6,
        )
        row.set_child(outer)

        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        outer.append(header_box)

        name_lbl = Gtk.Label(label=product.name, halign=Gtk.Align.START, hexpand=True)
        name_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        name_lbl.set_max_width_chars(40)
        header_box.append(name_lbl)

        size_lbl = Gtk.Label(label="…", halign=Gtk.Align.END)
        size_lbl.add_css_class("dim-label")
        size_lbl.add_css_class("caption")
        header_box.append(size_lbl)

        cancel_btn = Gtk.Button(
            icon_name="process-stop-symbolic",
            tooltip_text=_("Download abbrechen"),
            valign=Gtk.Align.CENTER,
        )
        cancel_btn.add_css_class("flat")
        cancel_btn.add_css_class("circular")
        cancel_btn.connect("clicked", self._on_cancel_download_clicked, product.artikelnummer)
        header_box.append(cancel_btn)

        progress_bar = Gtk.ProgressBar(hexpand=True)
        outer.append(progress_bar)

        return row, progress_bar, size_lbl

    # ── Download abgeschlossen ────────────────────────────────────────────────

    def _on_download_done(
        self, artikelnummer: str, success: bool, result: str, copy_to_pen: bool
    ) -> None:
        dl = self._active_downloads.pop(artikelnummer, None)
        if dl:
            self._active_dl_list.remove(dl["row"])

        if not self._active_downloads:
            self._active_dl_revealer.set_reveal_child(False)

        if not success:
            if result != CANCEL_SENTINEL:
                self._show_toast(_("Download fehlgeschlagen: {error}").format(error=result))
            return

        file_path = Path(result)
        self._show_toast(_("{name} heruntergeladen.").format(name=file_path.name))
        self._refresh_downloads_page()
        self._update_search_results()  # Statusicons aktualisieren

        if copy_to_pen and self._pen_path:
            error = gme.copy_to_pen(file_path, self._pen_path)
            if error:
                self._show_toast(_("Fehler beim Kopieren: {error}").format(error=error))
            else:
                self._show_toast(_("Auf Stift kopiert."))
                self._update_pen_view()
                self._update_search_results()
