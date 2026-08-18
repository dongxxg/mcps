"""TDD RED tests for PaginatedModel — page slicing over SheetData.

These tests deliberately assume the API described in the design doc
(DEFAULT_PAGE_SIZE = 500, current_page starting at 1). Running them before the
implementation exists proves the tests catch a missing module.
"""

from __future__ import annotations

from excelops.backends.models import SheetData
from excelops_gui.models.paginated_model import DEFAULT_PAGE_SIZE, PaginatedModel


def _make_rows(n: int) -> tuple[tuple, ...]:
    return tuple((i, f"row_{i}") for i in range(n))


def test_default_page_size_is_500() -> None:
    assert DEFAULT_PAGE_SIZE == 500


def test_empty_sheetdata_yields_one_page(app) -> None:  # noqa: F811
    sd = SheetData(columns=("a",), rows=())
    model = PaginatedModel(sd, parent=None)
    assert model.total_rows == 0
    assert model.total_pages == 1
    assert model.current_page == 1


def test_single_page_when_under_page_size(app) -> None:  # noqa: F811
    sd = SheetData(columns=("a", "b"), rows=_make_rows(499))
    model = PaginatedModel(sd, parent=None)
    assert model.total_rows == 499
    assert model.total_pages == 1
    assert model.rowCount(None) == 499


def test_two_pages_when_over_page_size(app) -> None:  # noqa: F811
    sd = SheetData(columns=("a",), rows=_make_rows(501))
    model = PaginatedModel(sd, parent=None)
    assert model.total_rows == 501
    assert model.total_pages == 2


def test_row_count_returns_current_page_slice_size(app) -> None:  # noqa: F811
    sd = SheetData(columns=("a",), rows=_make_rows(1250))
    model = PaginatedModel(sd, parent=None)
    assert model.current_page == 1
    assert model.rowCount(None) == 500


def test_next_page_advances_slice(app) -> None:  # noqa: F811
    sd = SheetData(columns=("v",), rows=_make_rows(1000))
    model = PaginatedModel(sd, parent=None)
    first_row = model.row_value(0, 0)
    model.next_page()
    assert model.current_page == 2
    second_page_first = model.row_value(0, 0)
    assert second_page_first != first_row
    # page 2 should start at row index 500
    assert second_page_first == 500


def test_prev_page_returns_to_first_page(app) -> None:  # noqa: F811
    sd = SheetData(columns=("v",), rows=_make_rows(1000))
    model = PaginatedModel(sd, parent=None)
    model.next_page()
    model.prev_page()
    assert model.current_page == 1
    assert model.rowCount(None) == 500


def test_page_boundaries_do_not_overshoot(app) -> None:  # noqa: F811
    sd = SheetData(columns=("v",), rows=_make_rows(3))
    model = PaginatedModel(sd, parent=None)
    model.next_page()
    assert model.current_page == 1  # stays on first (and only) page


def test_last_page_partial_rows(app) -> None:  # noqa: F811
    sd = SheetData(columns=("v",), rows=_make_rows(1100))
    model = PaginatedModel(sd, parent=None)
    model.next_page()  # page 2
    model.next_page()  # page 3 (last, partial)
    assert model.current_page == 3
    assert model.rowCount(None) == 100
