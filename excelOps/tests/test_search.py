"""Tests for ``search_files`` — cross-file directory search by priority conditions."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from openpyxl import Workbook

from excelops import SearchError, search_files
from excelops.backends.models import SheetData
from excelops.search import _match_rows, _values_equal


# ─── xlsx fixtures ──────────────────────────────────────────────────────────

def _write_xlsx(path: Path, sheets: dict[str, tuple[tuple[str, ...], list[tuple]]]) -> None:
    """Helper: write a multi-sheet xlsx file from column/row specs."""
    wb = Workbook()
    wb.remove(wb.active)
    for name, (cols, rows) in sheets.items():
        ws = wb.create_sheet(name)
        ws.append(cols)
        for row in rows:
            ws.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def _tmp_xlsx(tmp_path: Path, filename: str, sheets: dict[str, tuple[tuple[str, ...], list[tuple]]]) -> Path:
    path = tmp_path / filename
    _write_xlsx(path, sheets)
    return path


# ─── _values_equal (pure) ──────────────────────────────────────────────────

def test_values_equal_same_type() -> None:
    assert _values_equal("abc", "abc") is True
    assert _values_equal("abc", "def") is False
    assert _values_equal(42, 42) is True
    assert _values_equal(3.14, 3.14) is True


def test_values_equal_int_float_python_native() -> None:
    # Python native: 123 == 123.0 is True — we preserve this behavior.
    assert _values_equal(123, 123.0) is True


def test_values_equal_int_str_not_equal() -> None:
    # Type-faithful: int and str with same digits are NOT equal.
    assert _values_equal(123, "123") is False


def test_values_equal_none() -> None:
    assert _values_equal(None, None) is True
    assert _values_equal(None, "x") is False


# ─── _match_rows (pure) ────────────────────────────────────────────────────

def _sd(cols, rows) -> SheetData:
    return SheetData(columns=tuple(cols), rows=tuple(rows))


def test_match_rows_first_priority_wins() -> None:
    sd = _sd(["a", "b"], [("x", "y"), ("a_val", "b_val")])
    hits = _match_rows(sd, [("a", "a_val"), ("b", "b_val")])
    assert len(hits) == 1
    assert hits[0][1] == 0   # priority 0 (first condition)


def test_match_rows_fallback_to_second_priority() -> None:
    sd = _sd(["a", "b"], [("x", "b_val"), ("y", "b_val")])
    hits = _match_rows(sd, [("a", "a_val"), ("b", "b_val")])
    assert len(hits) == 2
    assert all(h[1] == 1 for h in hits)   # priority 1


def test_match_rows_no_match() -> None:
    sd = _sd(["a"], [("nope",)])
    hits = _match_rows(sd, [("a", "a_val"), ("b", "b_val")])
    assert hits == []


def test_match_rows_missing_column_skipped() -> None:
    sd = _sd(["b"], [("b_val",)])
    # "a" column doesn't exist → skip to "b" condition.
    hits = _match_rows(sd, [("a", "a_val"), ("b", "b_val")])
    assert len(hits) == 1
    assert hits[0][2] == "b"


def test_match_rows_all_conditions_missing() -> None:
    sd = _sd(["c"], [("c_val",)])
    hits = _match_rows(sd, [("a", "a_val"), ("b", "b_val")])
    assert hits == []


# ─── search_files — integration ─────────────────────────────────────────────

def test_single_file_single_sheet(tmp_path: Path) -> None:
    _tmp_xlsx(
        tmp_path, "price.xlsx",
        {"价格表": (
            ("编码", "名称", "单价"),
            [("A001", "牛奶", 3.5), ("A002", "面包", 2.0)],
        )},
    )
    result = search_files(tmp_path, [("编码", "A001")])

    assert result.columns[:4] == ("__file__", "__sheet__", "__match_field__", "__priority__")
    assert "编码" in result.columns
    assert len(result.rows) == 1
    row = result.rows[0]
    assert row[0] == "price.xlsx"
    assert row[1] == "价格表"
    assert row[2] == "编码"
    assert row[3] == 0


def test_priority_fallback_across_files(tmp_path: Path) -> None:
    _tmp_xlsx(
        tmp_path, "price_A.xlsx",
        {"s": (("编码", "条码", "名称"), [("A001", "6901", "牛奶")])},
    )
    _tmp_xlsx(
        tmp_path, "price_B.xlsx",
        {"s": (("编码", "条码", "名称"), [("X999", "6901", "面包")])},
    )
    result = search_files(tmp_path, [("编码", "A001"), ("条码", "6901")])

    priorities = [r[3] for r in result.rows]
    assert priorities[0] == 0   # price_A matched by 编码
    assert priorities[1] == 1   # price_B matched by 条码


def test_all_sheets_scanned(tmp_path: Path) -> None:
    _tmp_xlsx(
        tmp_path, "multi.xlsx",
        {
            "sheet1": (("编码",), [("X000",)]),
            "sheet2": (("编码",), [("A001",)]),
        },
    )
    result = search_files(tmp_path, [("编码", "A001")])
    assert len(result.rows) == 1
    assert result.rows[0][1] == "sheet2"


def test_empty_sheet_skipped(tmp_path: Path) -> None:
    _tmp_xlsx(
        tmp_path, "empty.xlsx",
        {"空表": (("编码",), [])},
    )
    result = search_files(tmp_path, [("编码", "A001")])
    assert result.rows == ()


def test_column_union_with_none_fill(tmp_path: Path) -> None:
    _tmp_xlsx(
        tmp_path, "a.xlsx",
        {"s": (("编码", "单价"), [("A001", 3.5)])},
    )
    _tmp_xlsx(
        tmp_path, "b.xlsx",
        {"s": (("编码", "市场价"), [("A001", 4.0)])},
    )
    result = search_files(tmp_path, [("编码", "A001")])

    cols = result.columns
    assert "单价" in cols
    assert "市场价" in cols

    price_idx = cols.index("单价")
    market_idx = cols.index("市场价")
    files = [r[0] for r in result.rows]
    assert len(files) == 2

    # a.xlsx row has 单价 but no 市场价
    a_row = next(r for r in result.rows if r[0] == "a.xlsx")
    assert a_row[price_idx] == 3.5
    assert a_row[market_idx] is None

    # b.xlsx row has 市场价 but no 单价
    b_row = next(r for r in result.rows if r[0] == "b.xlsx")
    assert b_row[price_idx] is None
    assert b_row[market_idx] == 4.0


def test_result_sorted_by_priority_then_file(tmp_path: Path) -> None:
    _tmp_xlsx(tmp_path, "a.xlsx", {"s": (("编码", "条码"), [("A001", "6901")])})
    _tmp_xlsx(tmp_path, "b.xlsx", {"s": (("编码", "条码"), [("X999", "6901")])})

    result = search_files(tmp_path, [("编码", "A001"), ("条码", "6901")])
    files = [r[0] for r in result.rows]
    # priority=0 (a.xlsx) before priority=1 (b.xlsx)
    assert files[0] == "a.xlsx"
    assert files[1] == "b.xlsx"


def test_no_match_returns_empty(tmp_path: Path) -> None:
    _tmp_xlsx(tmp_path, "price.xlsx", {"s": (("编码",), [("A001",)])})
    result = search_files(tmp_path, [("编码", "NOTEXIST")])
    assert result.rows == ()
    assert "__file__" in result.columns


def test_ignores_non_xlsx(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("ignore me")
    _tmp_xlsx(tmp_path, "price.xlsx", {"s": (("编码",), [("A001",)])})
    result = search_files(tmp_path, [("编码", "A001")])
    assert len(result.rows) == 1


def test_directory_not_found() -> None:
    with pytest.raises(SearchError, match="does not exist"):
        search_files("/nonexistent/path/xyz", [("编码", "A001")])


def test_empty_conditions() -> None:
    with pytest.raises(SearchError, match="must not be empty"):
        search_files(Path("."), [])


def test_invalid_field_name(tmp_path: Path) -> None:
    with pytest.raises(SearchError, match="invalid field name"):
        search_files(tmp_path, [("", "value")])


def test_no_xlsx_files(tmp_path: Path) -> None:
    (tmp_path / "readme.md").write_text("hi")
    with pytest.raises(SearchError, match="no .xlsx files"):
        search_files(tmp_path, [("编码", "A001")])


# ─── search_error hierarchy ─────────────────────────────────────────────────

def test_search_error_is_excelops_error() -> None:
    from excelops import ExcelOpsError
    assert issubclass(SearchError, ExcelOpsError)