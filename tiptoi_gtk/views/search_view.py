"""Suche-Tab: Suchfeld, Jahresfilter und Produktliste."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk

from tiptoi_gtk import _
from tiptoi_gtk.backend import catalog
from tiptoi_gtk.model.product import Product


class SearchViewMixin:
    """Mixin für den Suche-Tab."""

    # ── Aufbau ────────────────────────────────────────────────────────────────

    def _build_search_view(self) -> None:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._view_stack.add_titled_with_icon(
            outer, "search", _("Suchen"), "system-search-symbolic"
        )

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
            placeholder_text=_("Produktname oder Artikelnummer…"),
        )
        self._search_entry.connect("search-changed", self._on_search_changed)
        controls_box.append(self._search_entry)

        # Jahresfilter
        filter_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        controls_box.append(filter_box)
        filter_box.append(Gtk.Label(label=_("Jahr:")))

        self._year_dropdown = Gtk.DropDown(
            hexpand=True,
            tooltip_text=_("Nach Erscheinungsjahr filtern"),
        )
        self._year_model = Gtk.StringList.new([_("Alle Jahre")])
        self._year_dropdown.set_model(self._year_model)
        filter_box.append(self._year_dropdown)

        # Scrollbare Produktliste
        scrolled = Gtk.ScrolledWindow(vexpand=True)
        outer.append(scrolled)

        clamp = Adw.Clamp(maximum_size=800, margin_bottom=18)
        scrolled.set_child(clamp)

        results_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            margin_start=12, margin_end=12, margin_top=4,
        )
        clamp.set_child(results_box)

        self._result_count_label = Gtk.Label(
            margin_bottom=4,
            halign=Gtk.Align.START,
            visible=False,
        )
        self._result_count_label.add_css_class("dim-label")
        self._result_count_label.add_css_class("caption")
        results_box.append(self._result_count_label)

        self._no_results_label = Gtk.Label(
            label=_("Keine Produkte gefunden."),
            margin_top=32,
            visible=False,
        )
        self._no_results_label.add_css_class("dim-label")
        results_box.append(self._no_results_label)

        self._loading_label = Gtk.Label(
            label=_("Produktliste wird geladen…"),
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

        # Signal erst verbinden, nachdem _search_results_list existiert
        self._year_dropdown.connect("notify::selected", self._on_year_changed)

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def _on_search_changed(self, _entry: Gtk.SearchEntry) -> None:
        self._update_search_results()

    def _on_year_changed(self, dropdown: Gtk.DropDown, _param) -> None:
        idx = dropdown.get_selected()
        if idx == 0:
            self._selected_year = None
        else:
            year_idx = idx - 1
            if 0 <= year_idx < len(self._available_years):
                self._selected_year = self._available_years[year_idx]
        self._update_search_results()

    # ── Logik ─────────────────────────────────────────────────────────────────

    def _get_filtered_products(self) -> list[Product]:
        query = self._search_entry.get_text()
        results = catalog.search_products(query, self._products)
        if self._selected_year is not None:
            results = [p for p in results if p.year == self._selected_year]
        return results

    def _update_search_results(self) -> None:
        results = self._get_filtered_products()

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
        n = len(results)
        self._result_count_label.set_label(_("{n} Produkte").format(n=n))

        for product in results:
            self._search_results_list.append(self._make_product_row(product))

    def _make_product_row(self, product: Product) -> Adw.ActionRow:
        year_str = f" · {product.year}" if product.year else ""
        row = Adw.ActionRow(
            title=product.name,
            subtitle=_("Nr. {nr}{year}").format(nr=product.artikelnummer, year=year_str),
        )

        # Statusanzeige (Prefix): Bereits auf Stift oder lokal vorhanden
        if self._is_on_pen(product):
            badge = Gtk.Image(icon_name="media-removable-symbolic", pixel_size=16)
            badge.set_tooltip_text(_("Bereits auf dem Stift"))
            badge.add_css_class("success")
            row.add_prefix(badge)
        elif self._is_downloaded(product):
            badge = Gtk.Image(icon_name="emblem-ok-symbolic", pixel_size=16)
            badge.set_tooltip_text(_("Bereits heruntergeladen"))
            badge.add_css_class("accent")
            row.add_prefix(badge)

        if product.download_url:
            # Direkt auf Stift (nur wenn Stift verbunden)
            if self._pen_path:
                pen_btn = Gtk.Button(
                    icon_name="media-removable-symbolic",
                    tooltip_text=_("Herunterladen und auf Stift kopieren"),
                    valign=Gtk.Align.CENTER,
                )
                pen_btn.add_css_class("flat")
                pen_btn.connect("clicked", self._on_download_to_pen_clicked, product)
                row.add_suffix(pen_btn)

            dl_btn = Gtk.Button(
                icon_name="folder-download-symbolic",
                tooltip_text=_("Herunterladen"),
                valign=Gtk.Align.CENTER,
            )
            dl_btn.add_css_class("flat")
            dl_btn.connect("clicked", self._on_download_clicked, product)
            row.add_suffix(dl_btn)
        else:
            lbl = Gtk.Label(label=_("Kein Download"))
            lbl.add_css_class("dim-label")
            row.add_suffix(lbl)

        return row
