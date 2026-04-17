"""
Hauptfenster der tiptoi-gtk Anwendung.

Layout:
    AdwApplicationWindow
    └── AdwToastOverlay
        └── AdwToolbarView
            ├── [top] AdwHeaderBar
            │   ├── title: AdwViewSwitcher  (immer sichtbar, keine untere Leiste)
            │   └── end:   [Einstellungen] [Menü → Über]
            ├── [content]
            │   ├── AdwBanner      (Stift-Status)
            │   └── AdwViewStack
            │       ├── "search"    – Suche + Jahresfilter + Download/Stift
            │       ├── "pen"       – Stift-Infos + Dateien (mit Löschen)
            │       └── "downloads" – Lokale Downloads (mit Auf-Stift-Kopieren)
            └── [bottom] leer

Neue Features gegenüber Phase 1:
    - Keine untere Navigationsleiste (nur Header-Navigation)
    - Produktliste beim Start sofort sichtbar (kein leerer Zustand)
    - Jahresfilter (Dropdown, basiert auf _version aus CSV)
    - Einstellungsfenster: Download-Ordner konfigurierbar
    - About-Dialog
    - Löschen vom Stift mit AdwAlertDialog-Bestätigung
    - Download + direkt auf Stift kopieren (wenn Stift verbunden)
"""

import re
import threading
from pathlib import Path
from typing import Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk

from tiptoi_gtk.backend import catalog, gme
from tiptoi_gtk.backend import settings_manager as settings
from tiptoi_gtk.backend.downloader import download_gme
from tiptoi_gtk.backend.pen import PenMonitor
from tiptoi_gtk.model.product import Product

_ALL_YEARS_LABEL = "Alle Jahre"


class TiptoiWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

        self._products: list[Product] = []
        self._available_years: list[int] = []
        self._pen_path: Optional[str] = None
        self._pen_file_rows: list[tuple[Adw.ActionRow, Path]] = []
        self._downloading = False
        self._selected_year: Optional[int] = None

        self._build_ui()
        self._setup_pen_monitor()
        self._load_catalog_async()

    # ══════════════════════════════════════════════════════════════════════════
    # UI-Aufbau
    # ══════════════════════════════════════════════════════════════════════════

    def _build_ui(self) -> None:
        self.set_title("TipToi Manager")
        self.set_default_size(650, 720)
        self.set_icon_name("tiptoi-gtk")

        self._toast_overlay = Adw.ToastOverlay()
        self.set_content(self._toast_overlay)

        toolbar_view = Adw.ToolbarView()
        self._toast_overlay.set_child(toolbar_view)

        # ── Header Bar ────────────────────────────────────────────────────────
        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        self._view_stack = Adw.ViewStack(vexpand=True)

        # ViewSwitcher immer im Header, keine untere Leiste
        header_switcher = Adw.ViewSwitcher(
            policy=Adw.ViewSwitcherPolicy.WIDE,
            stack=self._view_stack,
        )
        header.set_title_widget(header_switcher)

        # Hamburger-Menü (Einstellungen + Über)
        menu = Gio.Menu()
        menu.append("Einstellungen", "win.preferences")
        menu.append("Über TipToi Manager", "win.about")
        menu_button = Gtk.MenuButton(
            icon_name="open-menu-symbolic",
            tooltip_text="Menü",
            menu_model=menu,
        )
        header.pack_end(menu_button)

        # GActions
        prefs_action = Gio.SimpleAction.new("preferences", None)
        prefs_action.connect("activate", self._show_preferences)
        self.add_action(prefs_action)

        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self._show_about)
        self.add_action(about_action)

        # ── Hauptinhalt ───────────────────────────────────────────────────────
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        toolbar_view.set_content(main_box)

        self._pen_banner = Adw.Banner(
            title="Stift verbunden",
            button_label="Anzeigen",
            revealed=False,
        )
        self._pen_banner.connect("button-clicked", self._on_pen_banner_clicked)
        main_box.append(self._pen_banner)

        main_box.append(self._view_stack)

        # ── Views ─────────────────────────────────────────────────────────────
        self._build_search_view()
        self._build_pen_view()
        self._build_downloads_view()

        self._view_stack.connect("notify::visible-child", self._on_view_changed)

    # ── View 1: Suchen ────────────────────────────────────────────────────────

    def _build_search_view(self) -> None:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._view_stack.add_titled_with_icon(
            outer, "search", "Suchen", "system-search-symbolic"
        )

        # Suchfeld + Jahresfilter in einem Clamp
        controls_clamp = Adw.Clamp(maximum_size=800)
        outer.append(controls_clamp)

        controls_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            margin_start=12, margin_end=12,
            margin_top=12, margin_bottom=6,
            spacing=6,
        )
        controls_clamp.set_child(controls_box)

        self._search_entry = Gtk.SearchEntry(
            placeholder_text="Produktname oder Artikelnummer…",
        )
        self._search_entry.connect("search-changed", self._on_search_changed)
        controls_box.append(self._search_entry)

        # Jahresfilter
        filter_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        controls_box.append(filter_box)

        filter_box.append(Gtk.Label(label="Jahr:"))

        self._year_dropdown = Gtk.DropDown(
            hexpand=True,
            tooltip_text="Nach Erscheinungsjahr filtern",
        )
        self._year_model = Gtk.StringList.new([_ALL_YEARS_LABEL])
        self._year_dropdown.set_model(self._year_model)
        filter_box.append(self._year_dropdown)

        # Fortschrittsbalken (nur während Download sichtbar)
        self._download_progress = Gtk.ProgressBar(
            margin_start=12, margin_end=12, margin_bottom=4,
            visible=False,
        )
        outer.append(self._download_progress)

        # Produktliste
        scrolled = Gtk.ScrolledWindow(vexpand=True)
        outer.append(scrolled)

        clamp = Adw.Clamp(maximum_size=800, margin_bottom=18)
        scrolled.set_child(clamp)

        results_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            margin_start=12, margin_end=12, margin_top=4,
        )
        clamp.set_child(results_box)

        # Statuszeile: "X Produkte" – innerhalb des Clamps, damit sie beim
        # Verbreitern des Fensters am Inhaltsblock verankert bleibt
        self._result_count_label = Gtk.Label(
            margin_bottom=4,
            halign=Gtk.Align.START,
            visible=False,
        )
        self._result_count_label.add_css_class("dim-label")
        self._result_count_label.add_css_class("caption")
        results_box.append(self._result_count_label)

        self._no_results_label = Gtk.Label(
            label="Keine Produkte gefunden.",
            margin_top=32,
            visible=False,
        )
        self._no_results_label.add_css_class("dim-label")
        results_box.append(self._no_results_label)

        self._loading_label = Gtk.Label(
            label="Produktliste wird geladen…",
            margin_top=32,
            visible=True,
        )
        self._loading_label.add_css_class("dim-label")
        results_box.append(self._loading_label)

        self._search_results_list = Gtk.ListBox(
            selection_mode=Gtk.SelectionMode.NONE,
            visible=False,
        )
        self._search_results_list.add_css_class("boxed-list")
        results_box.append(self._search_results_list)

        # Signal erst hier verbinden, nachdem _search_results_list existiert
        self._year_dropdown.connect("notify::selected", self._on_year_changed)

    # ── View 2: Stift ─────────────────────────────────────────────────────────

    def _build_pen_view(self) -> None:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._view_stack.add_titled_with_icon(
            outer, "pen", "Stift", "media-removable-symbolic"
        )

        self._pen_page_stack = Gtk.Stack(vexpand=True)
        outer.append(self._pen_page_stack)

        not_connected = Adw.StatusPage(
            icon_name="media-removable-symbolic",
            title="Kein Stift verbunden",
            description="Schließe deinen TipToi-Stift über USB an.",
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

        # Stift-Info
        info_group = Adw.PreferencesGroup(title="Stift-Informationen")
        self._pen_content_box.append(info_group)

        self._pen_path_row = Adw.ActionRow(title="Pfad", subtitle="–")
        info_group.add(self._pen_path_row)

        self._pen_storage_row = Adw.ActionRow(title="Speicher", subtitle="–")
        info_group.add(self._pen_storage_row)

        # Installierte Dateien (Gruppe wird dynamisch befüllt)
        self._pen_files_group = Adw.PreferencesGroup(title="Installierte Produkte")
        self._pen_content_box.append(self._pen_files_group)

        self._pen_page_stack.set_visible_child_name("disconnected")

    # ── View 3: Downloads ─────────────────────────────────────────────────────

    def _build_downloads_view(self) -> None:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._view_stack.add_titled_with_icon(
            outer, "downloads", "Downloads", "folder-download-symbolic"
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
            label="Ordner öffnen",
            icon_name="folder-open-symbolic",
            tooltip_text="Download-Ordner im Dateimanager öffnen",
        )
        open_btn.add_css_class("flat")
        open_btn.connect("clicked", self._on_open_downloads_folder)
        action_bar.append(open_btn)

        self._downloads_page_stack = Gtk.Stack(vexpand=True)
        outer.append(self._downloads_page_stack)

        self._downloads_page_stack.add_named(
            Adw.StatusPage(
                icon_name="folder-download-symbolic",
                title="Keine Downloads",
                description="Heruntergeladene Dateien erscheinen hier.",
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

        self._downloads_list = Gtk.ListBox(
            selection_mode=Gtk.SelectionMode.NONE,
        )
        self._downloads_list.add_css_class("boxed-list")
        dl_box.append(self._downloads_list)

        self._downloads_page_stack.set_visible_child_name("empty")

    # ══════════════════════════════════════════════════════════════════════════
    # Backend-Initialisierung
    # ══════════════════════════════════════════════════════════════════════════

    def _setup_pen_monitor(self) -> None:
        self._pen_monitor = PenMonitor(
            on_connected=self._on_pen_connected,
            on_disconnected=self._on_pen_disconnected,
        )
        existing = self._pen_monitor.scan_existing_mounts()
        if existing:
            self._on_pen_connected(existing)

    def _load_catalog_async(self) -> None:
        def worker() -> None:
            products, error = catalog.fetch_and_load()
            GLib.idle_add(self._on_catalog_loaded, products, error)

        threading.Thread(target=worker, daemon=True).start()

    # ══════════════════════════════════════════════════════════════════════════
    # Callbacks: Katalog
    # ══════════════════════════════════════════════════════════════════════════

    def _on_catalog_loaded(self, products: list[Product], error: Optional[str]) -> None:
        self._products = products
        self._loading_label.set_visible(False)

        if error:
            self._show_toast(f"Katalog-Fehler: {error}")

        # Jahresfilter befüllen
        self._available_years = catalog.available_years(products)
        for year in self._available_years:
            self._year_model.append(str(year))

        # Produktliste direkt anzeigen
        self._update_search_results()
        self._refresh_downloads_page()

    # ══════════════════════════════════════════════════════════════════════════
    # Suche & Filter
    # ══════════════════════════════════════════════════════════════════════════

    def _on_search_changed(self, _entry: Gtk.SearchEntry) -> None:
        self._update_search_results()

    def _on_year_changed(self, dropdown: Gtk.DropDown, _param) -> None:
        idx = dropdown.get_selected()
        if idx == 0:
            self._selected_year = None
        else:
            year_idx = idx - 1  # Offset für "Alle Jahre"
            if 0 <= year_idx < len(self._available_years):
                self._selected_year = self._available_years[year_idx]
        self._update_search_results()

    def _get_filtered_products(self) -> list[Product]:
        query = self._search_entry.get_text()
        results = catalog.search_products(query, self._products)
        if self._selected_year is not None:
            results = [p for p in results if p.year == self._selected_year]
        return results

    def _update_search_results(self) -> None:
        results = self._get_filtered_products()

        # Alte Zeilen entfernen
        while (child := self._search_results_list.get_first_child()) is not None:
            self._search_results_list.remove(child)

        if not results:
            self._no_results_label.set_visible(True)
            self._search_results_list.set_visible(False)
            self._result_count_label.set_visible(False)
            return

        self._no_results_label.set_visible(False)
        self._search_results_list.set_visible(True)
        self._result_count_label.set_visible(True)
        self._result_count_label.set_label(f"{len(results)} Produkte")

        for product in results:
            row = self._make_product_row(product)
            self._search_results_list.append(row)

    def _make_product_row(self, product: Product) -> Adw.ActionRow:
        year_str = f" · {product.year}" if product.year else ""
        row = Adw.ActionRow(
            title=product.name,
            subtitle=f"Nr. {product.artikelnummer}{year_str}",
        )

        if product.download_url:
            # Direkt auf Stift (nur wenn Stift verbunden)
            if self._pen_path:
                pen_btn = Gtk.Button(
                    icon_name="media-removable-symbolic",
                    tooltip_text="Herunterladen und auf Stift kopieren",
                    valign=Gtk.Align.CENTER,
                )
                pen_btn.add_css_class("flat")
                pen_btn.connect("clicked", self._on_download_to_pen_clicked, product)
                row.add_suffix(pen_btn)

            # Download
            dl_btn = Gtk.Button(
                icon_name="folder-download-symbolic",
                tooltip_text="Herunterladen",
                valign=Gtk.Align.CENTER,
            )
            dl_btn.add_css_class("flat")
            dl_btn.connect("clicked", self._on_download_clicked, product)
            row.add_suffix(dl_btn)
        else:
            no_url = Gtk.Label(label="Kein Download")
            no_url.add_css_class("dim-label")
            row.add_suffix(no_url)

        return row

    # ══════════════════════════════════════════════════════════════════════════
    # Download
    # ══════════════════════════════════════════════════════════════════════════

    def _dest_path(self, product: Product) -> Path:
        name_safe = re.sub(r"[^a-zA-Z0-9äöüÄÖÜß_-]", "_", product.name)[:40]
        return settings.download_dir() / f"{product.artikelnummer}_{name_safe}.gme"

    def _on_download_clicked(self, _btn: Gtk.Button, product: Product) -> None:
        self._start_download(product, copy_to_pen_after=False)

    def _on_download_to_pen_clicked(self, _btn: Gtk.Button, product: Product) -> None:
        self._start_download(product, copy_to_pen_after=True)

    def _start_download(self, product: Product, copy_to_pen_after: bool) -> None:
        if self._downloading:
            self._show_toast("Es läuft bereits ein Download.")
            return

        dest = self._dest_path(product)
        self._downloading = True
        self._download_progress.set_visible(True)
        self._download_progress.set_fraction(0.0)
        self._show_toast(f"Download: {product.name}")

        download_gme(
            url=product.download_url,
            dest=dest,
            progress_cb=self._on_download_progress,
            done_cb=lambda ok, result: self._on_download_done(ok, result, copy_to_pen_after),
        )

    def _on_download_progress(self, fraction: float) -> None:
        self._download_progress.set_fraction(fraction)

    def _on_download_done(self, success: bool, result: str, copy_to_pen: bool) -> None:
        self._downloading = False
        self._download_progress.set_visible(False)

        if not success:
            self._show_toast(f"Download fehlgeschlagen: {result}")
            return

        self._show_toast("Download abgeschlossen.")
        self._refresh_downloads_page()

        if copy_to_pen and self._pen_path:
            error = gme.copy_to_pen(Path(result), self._pen_path)
            if error:
                self._show_toast(f"Fehler beim Kopieren: {error}")
            else:
                self._show_toast("Auf Stift kopiert.")
                self._update_pen_view()

    # ══════════════════════════════════════════════════════════════════════════
    # Stift
    # ══════════════════════════════════════════════════════════════════════════

    def _on_pen_connected(self, path: str) -> None:
        self._pen_path = path
        self._pen_banner.set_title(f"Stift verbunden: {path}")
        self._pen_banner.set_revealed(True)
        self._update_pen_view()
        # Suchergebnisse neu aufbauen (Stift-Button erscheint)
        self._update_search_results()

    def _on_pen_disconnected(self, _path: str) -> None:
        self._pen_path = None
        self._pen_banner.set_revealed(False)
        self._pen_page_stack.set_visible_child_name("disconnected")
        self._show_toast("Stift getrennt.")
        # Stift-Button aus Suchergebnissen entfernen
        self._update_search_results()

    def _on_pen_banner_clicked(self, _banner: Adw.Banner) -> None:
        self._view_stack.set_visible_child_name("pen")

    def _update_pen_view(self) -> None:
        if not self._pen_path:
            self._pen_page_stack.set_visible_child_name("disconnected")
            return

        self._pen_page_stack.set_visible_child_name("connected")
        self._pen_path_row.set_subtitle(self._pen_path)

        free, total = gme.pen_disk_info(self._pen_path)
        if total > 0:
            self._pen_storage_row.set_subtitle(
                f"{gme.format_size(free)} frei von {gme.format_size(total)}"
            )

        # Alte Datei-Zeilen entfernen
        for row, _ in self._pen_file_rows:
            self._pen_files_group.remove(row)
        self._pen_file_rows.clear()

        files = gme.list_gme_files(self._pen_path)

        if not files:
            row = Adw.ActionRow(title="Keine Produkte installiert")
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
                tooltip_text="Vom Stift löschen",
                valign=Gtk.Align.CENTER,
            )
            delete_btn.add_css_class("flat")
            delete_btn.add_css_class("error")
            delete_btn.connect("clicked", self._on_delete_from_pen_clicked, f)
            row.add_suffix(delete_btn)

            self._pen_files_group.add(row)
            self._pen_file_rows.append((row, f))

    def _on_delete_from_pen_clicked(self, _btn: Gtk.Button, gme_path: Path) -> None:
        dialog = Adw.AlertDialog(
            heading="Datei löschen?",
            body=f"\u201e{gme_path.name}\u201c wird dauerhaft vom Stift entfernt.",
        )
        dialog.add_response("cancel", "Abbrechen")
        dialog.add_response("delete", "Löschen")
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
            self._show_toast(f"Fehler beim Löschen: {error}")
        else:
            self._show_toast(f"{gme_path.name} gelöscht.")
            self._update_pen_view()

    # ══════════════════════════════════════════════════════════════════════════
    # Downloads
    # ══════════════════════════════════════════════════════════════════════════

    def _on_view_changed(self, stack: Adw.ViewStack, _param) -> None:
        if stack.get_visible_child_name() == "downloads":
            self._refresh_downloads_page()

    def _refresh_downloads_page(self) -> None:
        dl_dir = settings.download_dir()
        dl_dir.mkdir(parents=True, exist_ok=True)
        files = sorted(dl_dir.glob("*.gme"), key=lambda p: p.name.lower())

        while (child := self._downloads_list.get_first_child()) is not None:
            self._downloads_list.remove(child)

        if not files:
            self._downloads_page_stack.set_visible_child_name("empty")
            return

        self._downloads_page_stack.set_visible_child_name("list")
        for f in files:
            self._downloads_list.append(self._make_download_row(f))

    def _make_download_row(self, path: Path) -> Adw.ActionRow:
        product_name = self._find_product_name(path.stem) or path.stem
        row = Adw.ActionRow(
            title=product_name,
            subtitle=f"{path.name} · {gme.format_size(path.stat().st_size)}",
        )

        copy_btn = Gtk.Button(
            icon_name="media-removable-symbolic",
            tooltip_text="Auf Stift kopieren",
            valign=Gtk.Align.CENTER,
            sensitive=self._pen_path is not None,
        )
        copy_btn.add_css_class("flat")
        copy_btn.connect("clicked", self._on_copy_to_pen_clicked, path)
        row.add_suffix(copy_btn)

        return row

    def _on_copy_to_pen_clicked(self, _btn: Gtk.Button, path: Path) -> None:
        if not self._pen_path:
            self._show_toast("Kein Stift verbunden.")
            return
        error = gme.copy_to_pen(path, self._pen_path)
        if error:
            self._show_toast(f"Fehler: {error}")
        else:
            self._show_toast(f"{path.name} auf Stift kopiert.")
            self._update_pen_view()

    def _on_open_downloads_folder(self, _btn: Gtk.Button) -> None:
        dl_dir = settings.download_dir()
        dl_dir.mkdir(parents=True, exist_ok=True)
        Gio.AppInfo.launch_default_for_uri(dl_dir.as_uri(), None)

    # ══════════════════════════════════════════════════════════════════════════
    # Einstellungen
    # ══════════════════════════════════════════════════════════════════════════

    def _show_preferences(self, _action=None, _param=None) -> None:
        prefs = Adw.PreferencesWindow(transient_for=self, modal=True)
        prefs.set_title("Einstellungen")

        page = Adw.PreferencesPage(
            title="Allgemein",
            icon_name="preferences-system-symbolic",
        )
        prefs.add(page)

        # ── Download-Ordner ───────────────────────────────────────────────────
        dl_group = Adw.PreferencesGroup(title="Speicherort")
        page.add(dl_group)

        dl_entry_row = Adw.EntryRow(
            title="Download-Ordner",
            text=str(settings.download_dir()),
        )
        # Beim Verlassen des Feldes speichern
        dl_entry_row.connect("apply", self._on_dl_dir_entry_apply)
        dl_entry_row.connect("notify::text", lambda row, _: None)  # Eingabe erlauben

        choose_btn = Gtk.Button(
            icon_name="folder-open-symbolic",
            tooltip_text="Ordner wählen",
            valign=Gtk.Align.CENTER,
        )
        choose_btn.add_css_class("flat")
        choose_btn.connect("clicked", self._on_choose_download_dir, prefs, dl_entry_row)
        dl_entry_row.add_suffix(choose_btn)
        dl_group.add(dl_entry_row)

        # ── Produktliste ──────────────────────────────────────────────────────
        csv_group = Adw.PreferencesGroup(title="Produktliste")
        page.add(csv_group)

        # Cache-Alter (Tage) editierbar
        current_max_age = settings.get("csv_max_age_days")
        adjustment = Gtk.Adjustment(
            value=current_max_age,
            lower=1, upper=365, step_increment=1, page_increment=7,
        )
        age_spin_row = Adw.SpinRow(
            title="Cache-Gültigkeit",
            subtitle="Produktliste nach dieser Anzahl Tage neu laden",
            adjustment=adjustment,
            digits=0,
        )
        age_spin_row.connect("notify::value", self._on_csv_age_changed)
        csv_group.add(age_spin_row)

        # Download-URL
        url_entry_row = Adw.EntryRow(
            title="Download-URL",
            text=settings.get("csv_url"),
        )
        url_entry_row.connect("apply", self._on_csv_url_entry_apply)
        reset_url_btn = Gtk.Button(
            icon_name="edit-undo-symbolic",
            tooltip_text="Auf Standard zurücksetzen",
            valign=Gtk.Align.CENTER,
        )
        reset_url_btn.add_css_class("flat")
        reset_url_btn.connect(
            "clicked",
            lambda _: (
                url_entry_row.set_text("https://cdn.ravensburger.de/db/tiptoi.csv"),
                settings.set_value("csv_url", "https://cdn.ravensburger.de/db/tiptoi.csv"),
            ),
        )
        url_entry_row.add_suffix(reset_url_btn)
        csv_group.add(url_entry_row)

        # Cache-Status (schreibgeschützt)
        age = catalog.catalog_age_days()
        age_str = f"{age:.0f} Tage alt" if age is not None else "nicht vorhanden"
        cache_status_row = Adw.ActionRow(
            title="Aktueller Cache",
            subtitle=f"~/.cache/tiptoi-gtk/produkte.csv · {age_str}",
        )
        refresh_btn = Gtk.Button(
            label="Jetzt aktualisieren",
            valign=Gtk.Align.CENTER,
        )
        refresh_btn.add_css_class("flat")
        refresh_btn.connect("clicked", self._on_force_refresh_catalog, prefs)
        cache_status_row.add_suffix(refresh_btn)
        csv_group.add(cache_status_row)

        prefs.present()

    def _on_dl_dir_entry_apply(self, row: Adw.EntryRow) -> None:
        new_path = Path(row.get_text().strip())
        settings.set_download_dir(new_path)
        self._refresh_downloads_page()
        self._show_toast(f"Download-Ordner: {new_path}")

    def _on_csv_age_changed(self, spin_row: Adw.SpinRow, _param) -> None:
        settings.set_value("csv_max_age_days", int(spin_row.get_value()))

    def _on_csv_url_entry_apply(self, row: Adw.EntryRow) -> None:
        url = row.get_text().strip()
        if url:
            settings.set_value("csv_url", url)
            self._show_toast("URL gespeichert. Beim nächsten Aktualisieren wird sie verwendet.")

    def _on_choose_download_dir(
        self, _btn: Gtk.Button, parent: Gtk.Window, entry_row: Adw.EntryRow
    ) -> None:
        dialog = Gtk.FileDialog(title="Download-Ordner wählen")
        dialog.set_initial_folder(
            Gio.File.new_for_path(str(settings.download_dir()))
        )
        dialog.select_folder(parent, None, lambda d, r: self._on_download_dir_chosen(d, r, entry_row))

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
                self._show_toast(f"Download-Ordner: {new_path}")
        except GLib.Error:
            pass  # Nutzer hat abgebrochen

    def _on_force_refresh_catalog(self, _btn: Gtk.Button, prefs: Adw.PreferencesWindow) -> None:
        prefs.close()
        self._show_toast("Produktliste wird aktualisiert…")
        self._products = []
        self._available_years = []
        self._loading_label.set_visible(True)
        self._search_results_list.set_visible(False)

        # Jahr-Dropdown zurücksetzen
        while self._year_model.get_n_items() > 1:
            self._year_model.remove(self._year_model.get_n_items() - 1)
        self._year_dropdown.set_selected(0)
        self._selected_year = None

        def worker() -> None:
            products, error = catalog.fetch_and_load(force=True)
            GLib.idle_add(self._on_catalog_loaded, products, error)

        threading.Thread(target=worker, daemon=True).start()

    # ══════════════════════════════════════════════════════════════════════════
    # About
    # ══════════════════════════════════════════════════════════════════════════

    def _show_about(self, _action=None, _param=None) -> None:
        try:
            about = Adw.AboutDialog(
                application_name="TipToi Manager",
                application_icon="tiptoi-gtk",
                version="0.1.0",
                comments="Nativer GNOME-Manager für TipToi-Stifte unter Linux.",
                website="https://github.com/example/tiptoi-gtk",
                license_type=Gtk.License.GPL_3_0,
                developers=["Entwickler"],
                copyright="© 2024",
            )
            about.present(self)
        except AttributeError:
            # Fallback für libadwaita < 1.5
            about = Adw.AboutWindow(
                transient_for=self,
                application_name="TipToi Manager",
                application_icon="tiptoi-gtk",
                version="0.1.0",
                comments="Nativer GNOME-Manager für TipToi-Stifte unter Linux.",
                website="https://github.com/example/tiptoi-gtk",
                license_type=Gtk.License.GPL_3_0,
                developers=["Entwickler"],
                copyright="© 2024",
            )
            about.present()

    # ══════════════════════════════════════════════════════════════════════════
    # Hilfsmethoden
    # ══════════════════════════════════════════════════════════════════════════

    def _find_product_name(self, filename: str) -> Optional[str]:
        match = re.match(r"^(\d+)", filename)
        if match:
            artikelnr = match.group(1)
            for product in self._products:
                if product.artikelnummer == artikelnr:
                    return product.name
        return None

    def _show_toast(self, message: str, timeout: int = 3) -> None:
        toast = Adw.Toast(title=message, timeout=timeout)
        self._toast_overlay.add_toast(toast)
