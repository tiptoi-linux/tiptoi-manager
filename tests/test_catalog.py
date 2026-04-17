"""
Tests für tiptoi_gtk.backend.catalog
"""

import csv
import tempfile
from pathlib import Path

import pytest

from tiptoi_gtk.backend.catalog import (
    _detect_delimiter,
    _find_url_column_index,
    search_products,
)
from tiptoi_gtk.model.product import Product


# ── Hilfsfunktionen ────────────────────────────────────────────────────────────

def make_products(*names: str) -> list[Product]:
    return [
        Product(artikelnummer=str(10000 + i), name=name, download_url="https://example.com/x.gme")
        for i, name in enumerate(names)
    ]


# ── _detect_delimiter ──────────────────────────────────────────────────────────

def test_detect_delimiter_semicolon(tmp_path: Path) -> None:
    csv_file = tmp_path / "test.csv"
    csv_file.write_text("12345;Weltatlas;https://example.com/x.gme\n", encoding="utf-8")
    assert _detect_delimiter(csv_file) == ";"


def test_detect_delimiter_comma(tmp_path: Path) -> None:
    csv_file = tmp_path / "test.csv"
    csv_file.write_text("12345,Weltatlas,https://example.com/x.gme\n", encoding="utf-8")
    assert _detect_delimiter(csv_file) == ","


# ── _find_url_column_index ─────────────────────────────────────────────────────

def test_find_url_column_finds_https() -> None:
    row = ["12345", "Weltatlas", "https://cdn.ravensburger.de/12345.gme"]
    assert _find_url_column_index(row) == 2


def test_find_url_column_returns_minus_one_if_missing() -> None:
    row = ["12345", "Weltatlas", "kein-link"]
    assert _find_url_column_index(row) == -1


# ── search_products ────────────────────────────────────────────────────────────

def test_search_by_name() -> None:
    products = make_products("Weltatlas", "Mein Körper", "Erste Zahlen")
    results = search_products("weltatlas", products)
    assert len(results) == 1
    assert results[0].name == "Weltatlas"


def test_search_by_article_number() -> None:
    products = make_products("Weltatlas", "Mein Körper")
    results = search_products("10001", products)
    assert len(results) == 1
    assert results[0].name == "Mein Körper"


def test_search_case_insensitive() -> None:
    products = make_products("Weltatlas")
    assert search_products("WELTATLAS", products)
    assert search_products("wElTaTlAs", products)


def test_search_empty_query_returns_empty() -> None:
    products = make_products("Weltatlas", "Mein Körper")
    assert search_products("", products) == []
    assert search_products("   ", products) == []


def test_search_max_50_results() -> None:
    products = make_products(*[f"Produkt {i}" for i in range(100)])
    results = search_products("Produkt", products)
    assert len(results) == 50


def test_search_no_match_returns_empty() -> None:
    products = make_products("Weltatlas")
    assert search_products("xyzxyz", products) == []
