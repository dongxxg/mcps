"""Structural tests for MainWindow layout and basic wiring."""

from __future__ import annotations

from excelops_gui.main_window import MainWindow


def test_main_window_has_three_zones(app) -> None:  # noqa: F811
    win = MainWindow()
    win.show()
    # Central widget holds a vertical layout with toolbar + splitter
    splitter = win._splitter
    assert splitter.count() == 3


def test_main_window_default_title(app) -> None:  # noqa: F811
    win = MainWindow()
    assert "excelOps" in win.windowTitle()


def test_navigation_zone_present(app) -> None:  # noqa: F811
    win = MainWindow()
    assert hasattr(win, "_navigation")
    assert win._navigation is not None


def test_data_table_zone_present(app) -> None:  # noqa: F811
    win = MainWindow()
    assert hasattr(win, "_data_table")
    assert win._data_table is not None


def test_search_panel_is_first_tab(app) -> None:  # noqa: F811
    win = MainWindow()
    tab = win._tab
    assert tab.count() >= 1
    assert "搜索" in tab.tabText(0)


def test_open_file_loads_sheet_data(app, tmp_xlsx) -> None:  # noqa: F811
    """Simulate a sheet load without threading — call the loaded handler directly."""
    from excelops import read_sheet

    win = MainWindow()
    win.show()

    # Load synchronously (avoids waiting on worker thread in headless test)
    sd = read_sheet(str(tmp_xlsx), "sheet1")
    win._active_file = str(tmp_xlsx)
    win._active_sheet = "sheet1"
    win._on_sheet_loaded(sd)

    assert win._current_sheet_data is not None
    assert len(win._current_sheet_data.rows) == 3
    assert win._data_table.model.total_rows == 3


def test_search_no_file_shows_hint(app, tmp_xlsx) -> None:  # noqa: F811
    win = MainWindow()
    win.show()
    # No file loaded → single-file search should warn
    search_panel = win._panels.get("search")
    assert search_panel is not None
    win._on_search()
    assert "请先打开一个文件" in search_panel._status_label.text()
