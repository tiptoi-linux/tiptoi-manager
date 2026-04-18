"""Downloads-Tab: Lokale GME-Dateien und Kopieren auf den Stift."""

import re
from collections import defaultdict
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, Gtk

from tiptoi_gtk import _
from tiptoi_gtk.backend import gme
from tiptoi_gtk.backend import settings_manager as settings


class DownloadsViewMixin:
    """Mixin für den Downloads-Tab."""

    # ── Aufbau ────────────────────────────────────────────────────────────────

    def _build_downloads_view(self) -> None:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._view_stack.add_titled_with_icon(
            outer, "downloads", _("Downloads"), "folder-download-symbolic"
        )

        action_clamp = Adw.Clamp(maximum_size=800)
        outer.append(action_clamp)

        action_bar = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            margin_start=12, margin_end=12,
            margin_top=6, margin_bottom=6,
        )
        action_clamp.set_child(action_bar)

        open_btn = Gtk.Button(
            label=_("Ordner öffnen"),
            icon_name="folder-open-symbolic",
            tooltip_text=_("Download-Ordner im Dateimanager öffnen"),
        )
        open_btn.add_css_class("flat")
        open_btn.connect("clicked", self._on_open_downloads_folder)
        action_bar.append(open_btn)

        self._downloads_page_stack = Gtk.Stack(vexpand=True)
        outer.append(self._downloads_page_stack)

        self._downloads_page_stack.add_named(
            Adw.StatusPage(
                icon_name="folder-download-symbolic",
                title=_("Keine Downloads"),
                description=_("Heruntergeladene Dateien erscheinen hier."),
                vexpand=True,
            ),
            "empty",
        )

        downloads_scroll = Gtk.ScrolledWindow(vexpand=True)
        self._downloads_page_stack.add_named(downloads_scroll, "list")

        clamp = Adw.Clamp(maximum_size=800, margin_top=6, margin_bottom=18)
        downloads_scroll.set_child(clamp)

        dl_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            margin_start=12, margin_end=12,
        )
        clamp.set_child(dl_box)

        self._downloads_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self._downloads_list.add_css_class("boxed-list")
        dl_box.append(self._downloads_list)

        self._downloads_page_stack.set_visible_child_name("empty")

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def _on_view_changed(self, stack: Adw.ViewStack, _param) -> None:
        if stack.get_visible_child_name() == "downloads":
            self._refresh_downloads_page()

    def _on_copy_to_pen_clicked(self, _btn: Gtk.Button, path: Path) -> None:
        if not self._pen_path:
            self._show_toast(_("Kein Stift verbunden."))
            return
        error = gme.copy_to_pen(path, self._pen_path)
        if error:
            self._show_toast(_("Fehler: {error}").format(error=error))
        else:
            self._show_toast(_("{name} auf Stift kopiert.").format(name=path.name))
            self._update_pen_view()

    def _on_open_downloads_folder(self, _btn: Gtk.Button) -> None:
        dl_dir = settings.download_dir()
        dl_dir.mkdir(parents=True, exist_ok=True)
        Gio.AppInfo.launch_default_for_uri(dl_dir.as_uri(), None)

    # ── View-Aktualisierung ───────────────────────────────────────────────────

    def _refresh_downloads_page(self) -> None:
        dl_dir = settings.download_dir()
        dl_dir.mkdir(parents=True, exist_ok=True)
        files = sorted(dl_dir.glob("*.gme"), key=lambda p: p.name.lower())

        while (child := self._downloads_list.get_first_child()) is not None:
            self._downloads_list.remove(child)

        if not files:
            self._downloads_page_stack.set_visible_child_name("empty")
            return

        # Duplikate erkennen: mehrere Dateien mit gleicher Artikelnummer
        by_artikel: dict[str, list[Path]] = defaultdict(list)
        for f in files:
            m = re.match(r"^(\d+)", f.stem)
            key = m.group(1) if m else f.name
            by_artikel[key].append(f)

        self._downloads_page_stack.set_visible_child_name("list")
        for f in files:
            m = re.match(r"^(\d+)", f.stem)
            artikel = m.group(1) if m else None
            is_dup = bool(artikel and len(by_artikel[artikel]) > 1)
            self._downloads_list.append(self._make_download_row(f, is_dup))

    def _make_download_row(self, path: Path, is_duplicate: bool = False) -> Adw.ActionRow:
        product_name = self._find_product_name(path.stem) or path.stem
        row = Adw.ActionRow(
            title=product_name,
            subtitle=f"{path.name} · {gme.format_size(path.stat().st_size)}",
        )

        if is_duplicate:
            warn = Gtk.Image(icon_name="dialog-warning-symbolic", pixel_size=16)
            warn.set_tooltip_text(_("Mehrere Dateien für diese Artikelnummer vorhanden"))
            warn.add_css_class("warning")
            row.add_prefix(warn)

        copy_btn = Gtk.Button(
            icon_name="media-removable-symbolic",
            tooltip_text=_("Auf Stift kopieren"),
            valign=Gtk.Align.CENTER,
            sensitive=self._pen_path is not None,
        )
        copy_btn.add_css_class("flat")
        copy_btn.connect("clicked", self._on_copy_to_pen_clicked, path)
        row.add_suffix(copy_btn)

        return row
