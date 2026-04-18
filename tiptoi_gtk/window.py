"""
Hauptfenster der tiptoi-gtk Anwendung.

Layout:
    AdwApplicationWindow
    └── AdwToastOverlay
        └── AdwToolbarView
            ├── [top] AdwHeaderBar
            │   ├── title: AdwViewSwitcher  (WIDE, nur im Header)
            │   └── end:   [≡ Menü → Einstellungen / Über]
            ├── [content]
            │   ├── AdwBanner          (Stift-Status mit Label + Pfad)
            │   ├── Gtk.Revealer       (aktive Downloads – alle Views sichtbar)
            │   └── AdwViewStack
            │       ├── "search"    – Suche + Jahresfilter
            │       ├── "pen"       – Stift-Infos + Dateien
            │       └── "downloads" – Lokale Downloads
            └── [bottom] leer

Die drei Tabs und der Einstellungsdialog sind als Mixins ausgelagert:
    views/search_view.py      – SearchViewMixin
    views/pen_view.py         – PenViewMixin
    views/downloads_view.py   – DownloadsViewMixin
    views/download_manager.py – DownloadManagerMixin
    dialogs/preferences.py    – PreferencesDialogMixin
"""

import re
import threading
from pathlib import Path
from typing import Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk

from tiptoi_gtk import _
from tiptoi_gtk.backend import catalog
from tiptoi_gtk.backend import settings_manager as settings
from tiptoi_gtk.model.product import Product
from tiptoi_gtk.dialogs.preferences import PreferencesDialogMixin
from tiptoi_gtk.views.download_manager import DownloadManagerMixin
from tiptoi_gtk.views.downloads_view import DownloadsViewMixin
from tiptoi_gtk.views.pen_view import PenViewMixin
from tiptoi_gtk.views.search_view import SearchViewMixin


class TiptoiWindow(
    SearchViewMixin,
    PenViewMixin,
    DownloadsViewMixin,
    DownloadManagerMixin,
    PreferencesDialogMixin,
    Adw.ApplicationWindow,
):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

        self._products: list[Product] = []
        self._available_years: list[int] = []
        self._pen_path: Optional[str] = None
        self._pen_label: str = ""
        self._pen_file_rows: list[tuple[Adw.ActionRow, Path]] = []
        self._selected_year: Optional[int] = None

        # Aktive Downloads: artikelnummer → {event, row, progress, size_lbl}
        self._active_downloads: dict[str, dict] = {}

        self._build_ui()
        self._setup_pen_monitor()
        self._load_catalog_async()

    # ══════════════════════════════════════════════════════════════════════════
    # UI-Aufbau (Rahmen + gemeinsame Elemente)
    # ══════════════════════════════════════════════════════════════════════════

    def _build_ui(self) -> None:
        self.set_title("TipToi Manager")
        self.set_default_size(650, 720)
        self.set_icon_name("io.github.tiptoi_linux.TiptoiManager")

        self._toast_overlay = Adw.ToastOverlay()
        self.set_content(self._toast_overlay)

        toolbar_view = Adw.ToolbarView()
        self._toast_overlay.set_child(toolbar_view)

        # ── Header Bar ────────────────────────────────────────────────────────
        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        self._view_stack = Adw.ViewStack(vexpand=True)
        header_switcher = Adw.ViewSwitcher(
            policy=Adw.ViewSwitcherPolicy.WIDE,
            stack=self._view_stack,
        )
        header.set_title_widget(header_switcher)

        menu = Gio.Menu()
        menu.append(_("Einstellungen"), "win.preferences")
        menu.append(_("Über TipToi Manager"), "win.about")
        menu_button = Gtk.MenuButton(
            icon_name="open-menu-symbolic",
            tooltip_text=_("Menü"),
            menu_model=menu,
        )
        header.pack_end(menu_button)

        prefs_action = Gio.SimpleAction.new("preferences", None)
        prefs_action.connect("activate", self._show_preferences)
        self.add_action(prefs_action)

        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self._show_about)
        self.add_action(about_action)

        # ── Hauptinhalt ───────────────────────────────────────────────────────
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        toolbar_view.set_content(main_box)

        # Stift-Banner
        self._pen_banner = Adw.Banner(
            title=_("Stift verbunden"),
            button_label=_("Anzeigen"),
            revealed=False,
        )
        self._pen_banner.connect("button-clicked", self._on_pen_banner_clicked)
        main_box.append(self._pen_banner)

        # Aktive Downloads – Revealer (über allen Views sichtbar)
        self._active_dl_revealer = Gtk.Revealer(
            transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN,
            reveal_child=False,
        )
        main_box.append(self._active_dl_revealer)

        active_dl_clamp = Adw.Clamp(maximum_size=800)
        self._active_dl_revealer.set_child(active_dl_clamp)

        active_dl_outer = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            margin_start=12, margin_end=12,
            margin_top=8, margin_bottom=4,
            spacing=4,
        )
        active_dl_clamp.set_child(active_dl_outer)

        hdr_lbl = Gtk.Label(label=_("Aktive Downloads"), halign=Gtk.Align.START)
        hdr_lbl.add_css_class("caption")
        hdr_lbl.add_css_class("dim-label")
        active_dl_outer.append(hdr_lbl)

        self._active_dl_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self._active_dl_list.add_css_class("boxed-list")
        active_dl_outer.append(self._active_dl_list)

        main_box.append(self._view_stack)

        # ── Views (Mixins) ────────────────────────────────────────────────────
        self._build_search_view()
        self._build_pen_view()
        self._build_downloads_view()

        self._view_stack.connect("notify::visible-child", self._on_view_changed)

    # ══════════════════════════════════════════════════════════════════════════
    # Katalog laden
    # ══════════════════════════════════════════════════════════════════════════

    def _load_catalog_async(self) -> None:
        def worker() -> None:
            products, error = catalog.fetch_and_load()
            GLib.idle_add(self._on_catalog_loaded, products, error)

        threading.Thread(target=worker, daemon=True).start()

    def _on_catalog_loaded(self, products: list[Product], error: Optional[str]) -> None:
        self._products = products
        self._loading_label.set_visible(False)

        if error:
            self._show_toast(_("Katalog-Fehler: {error}").format(error=error))

        self._available_years = catalog.available_years(products)
        for year in self._available_years:
            self._year_model.append(str(year))

        self._update_search_results()
        self._refresh_downloads_page()

    # ══════════════════════════════════════════════════════════════════════════
    # Gemeinsame Hilfsmethoden
    # ══════════════════════════════════════════════════════════════════════════

    def _is_on_pen(self, product: Product) -> bool:
        if not self._pen_path:
            return False
        pen = Path(self._pen_path)
        return (
            any(pen.glob(f"{product.artikelnummer}_*.gme")) or
            any(pen.glob(f"{product.artikelnummer}_*.GME"))
        )

    def _is_downloaded(self, product: Product) -> bool:
        dl_dir = settings.download_dir()
        if not dl_dir.exists():
            return False
        return any(dl_dir.glob(f"{product.artikelnummer}_*.gme"))

    def _dest_path(self, product: Product) -> Path:
        name_safe = re.sub(r"[^a-zA-Z0-9äöüÄÖÜß_-]", "_", product.name)[:40]
        return settings.download_dir() / f"{product.artikelnummer}_{name_safe}.gme"

    def _find_product_name(self, filename: str) -> Optional[str]:
        m = re.match(r"^(\d+)", filename)
        if m:
            artikelnr = m.group(1)
            for product in self._products:
                if product.artikelnummer == artikelnr:
                    return product.name
        return None

    def _show_toast(self, message: str, timeout: int = 3) -> None:
        self._toast_overlay.add_toast(Adw.Toast(title=message, timeout=timeout))

    # ══════════════════════════════════════════════════════════════════════════
    # Über-Dialog
    # ══════════════════════════════════════════════════════════════════════════

    def _show_about(self, _action=None, _param=None) -> None:
        kwargs = dict(
            application_name="TipToi Manager",
            application_icon="tiptoi-gtk",
            version="1.0.0",
            comments=_("Nativer GNOME-Manager für TipToi-Stifte unter Linux."),
            website="https://github.com/tiptoi-linux/tiptoi-manager",
            license_type=Gtk.License.GPL_3_0,
            developers=["Manuel Simon"],
            copyright="© 2026",
        )
        try:
            about = Adw.AboutDialog(**kwargs)
            about.present(self)
        except AttributeError:
            # Fallback für libadwaita < 1.5
            about = Adw.AboutWindow(transient_for=self, **kwargs)
            about.present()
