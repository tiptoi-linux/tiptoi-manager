"""
Tests für tiptoi_gtk.backend.gme (Dateioperationen)

Die PenMonitor-Klasse selbst erfordert einen laufenden GLib-Mainloop und
einen echten GIO VolumeMonitor – diese werden in Unit-Tests nicht getestet.
Stattdessen testen wir die Hilfsfunktionen in gme.py.
"""

import tempfile
from pathlib import Path

import pytest

from tiptoi_gtk.backend.gme import (
    copy_to_pen,
    delete_from_pen,
    format_size,
    list_gme_files,
    pen_disk_info,
)


# ── list_gme_files ─────────────────────────────────────────────────────────────

def test_list_gme_files_finds_gme(tmp_path: Path) -> None:
    (tmp_path / "12345_Weltatlas.gme").write_bytes(b"dummy")
    (tmp_path / "67890_Zahlen.GME").write_bytes(b"dummy")  # Großbuchstaben
    (tmp_path / "readme.txt").write_bytes(b"text")

    files = list_gme_files(str(tmp_path))
    names = [f.name for f in files]

    assert "12345_Weltatlas.gme" in names
    assert "67890_Zahlen.GME" in names
    assert "readme.txt" not in names


def test_list_gme_files_sorted(tmp_path: Path) -> None:
    (tmp_path / "zzz.gme").write_bytes(b"x")
    (tmp_path / "aaa.gme").write_bytes(b"x")
    (tmp_path / "mmm.gme").write_bytes(b"x")

    files = list_gme_files(str(tmp_path))
    names = [f.name for f in files]
    assert names == sorted(names, key=str.lower)


def test_list_gme_files_empty_dir(tmp_path: Path) -> None:
    assert list_gme_files(str(tmp_path)) == []


# ── copy_to_pen ────────────────────────────────────────────────────────────────

def test_copy_to_pen_success(tmp_path: Path) -> None:
    source = tmp_path / "source.gme"
    source.write_bytes(b"gme content")
    pen = tmp_path / "pen"
    pen.mkdir()

    error = copy_to_pen(source, str(pen))

    assert error is None
    assert (pen / "source.gme").read_bytes() == b"gme content"


def test_copy_to_pen_nonexistent_source(tmp_path: Path) -> None:
    source = tmp_path / "missing.gme"  # existiert nicht
    pen = tmp_path / "pen"
    pen.mkdir()

    error = copy_to_pen(source, str(pen))
    assert error is not None


# ── delete_from_pen ────────────────────────────────────────────────────────────

def test_delete_from_pen_success(tmp_path: Path) -> None:
    gme_file = tmp_path / "test.gme"
    gme_file.write_bytes(b"data")

    error = delete_from_pen(gme_file)

    assert error is None
    assert not gme_file.exists()


def test_delete_from_pen_nonexistent(tmp_path: Path) -> None:
    gme_file = tmp_path / "missing.gme"
    error = delete_from_pen(gme_file)
    assert error is not None


# ── format_size ────────────────────────────────────────────────────────────────

def test_format_size_mb() -> None:
    assert "MB" in format_size(5 * 1024 * 1024)


def test_format_size_gb() -> None:
    assert "GB" in format_size(2 * 1024 * 1024 * 1024)


def test_format_size_small() -> None:
    assert "MB" in format_size(512 * 1024)


# ── pen_disk_info ──────────────────────────────────────────────────────────────

def test_pen_disk_info_valid_path(tmp_path: Path) -> None:
    free, total = pen_disk_info(str(tmp_path))
    assert total > 0
    assert free <= total


def test_pen_disk_info_invalid_path() -> None:
    free, total = pen_disk_info("/nonexistent/path/xyz")
    assert free == 0
    assert total == 0
