"""Regression tests for refreshing the pen view without a display or USB device."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

pytest.importorskip("gi")
from tiptoi_gtk.views import pen_view


@pytest.mark.parametrize("has_product", [False, True])
def test_refresh_connected_pen_preserves_gettext(tmp_path, monkeypatch, has_product):
    product = tmp_path / "example.gme"
    if has_product:
        product.write_bytes(b"example")
    files = [product] if has_product else []
    monkeypatch.setattr(pen_view.gme, "pen_disk_info", lambda path: (1024, 2048))
    monkeypatch.setattr(pen_view.gme, "list_gme_files", lambda path: files)
    action_row = Mock()
    monkeypatch.setattr(pen_view.Adw, "ActionRow", action_row)
    monkeypatch.setattr(pen_view.Gtk, "Button", Mock())
    old_row = Mock()
    view = SimpleNamespace(
        _pen_path=str(tmp_path),
        _pen_label="tiptoi",
        _pen_page_stack=Mock(),
        _pen_path_row=Mock(),
        _pen_storage_row=Mock(),
        _pen_files_group=Mock(),
        _pen_file_rows=[(old_row, Path("old.gme"))],
        _find_product_name=lambda stem: None,
        _on_delete_from_pen_clicked=Mock(),
    )

    pen_view.PenViewMixin._update_pen_view(view)

    view._pen_page_stack.set_visible_child_name.assert_called_once_with("connected")
    view._pen_storage_row.set_subtitle.assert_called_once_with(
        pen_view._("{free} frei von {total}").format(
            free=pen_view.gme.format_size(1024), total=pen_view.gme.format_size(2048)
        )
    )
    view._pen_files_group.remove.assert_called_once_with(old_row)
    view._pen_files_group.add.assert_called_once_with(action_row.return_value)
    assert view._pen_file_rows == [
        (action_row.return_value, product if has_product else Path())
    ]
