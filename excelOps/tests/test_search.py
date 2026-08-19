"""Tests for ``search_files`` — cross-file directory search by priority conditions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from openpyxl import Workbook

from excelops import SearchError, search_files
from excelops.backends.models import SheetData
from excelops.search import (
    _match_rows,
    _normalize_conditions,
    _values_contains,
    _values_equal,
)


# ─── xlsx fixtures ──────────────────────────────────────────────────────────

def _write_xlsx(
    path: Path,
    sheets: dict[str, tuple[tuple[str, ...], list[tuple]]],
) -> None:
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


def _tmp_xlsx(
    tmp_path: Path,
    filename: str,
    sheets: dict[str, tuple[tuple[str, ...], list[tuple]]],
) -> Path:
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
    # Python native: 123 == 123.0 is True.
    assert _values_equal(123, 123.0) is True


def test_values_equal_int_str_not_equal() -> None:
    # Numeric coercion: str digits equal to an int match (GUI input is always str).
    assert _values_equal(123, "123") is True
    # Non-numeric strings still do not match.
    assert _values_equal(123, "abc") is False


def test_values_equal_none() -> None:
    assert _values_equal(None, None) is True
    assert _values_equal(None, "x") is False


# ─── _values_contains (pure) ───────────────────────────────────────────────

def test_values_contains_match() -> None:
    assert _values_contains("牛奶 250ml", "牛奶") is True
    assert _values_contains("abc", "a") is True
    assert _values_contains("abc", "abc") is True


def test_values_contains_no_match() -> None:
    assert _values_contains("牛奶", "面包") is False
    assert _values_contains("", "x") is False


def test_values_contains_case_insensitive() -> None:
    assert _values_contains("ABC 123", "abc") is True
    assert _values_contains("纯牛奶", "牛奶") is True


def test_values_contains_numeric_coerced_to_string() -> None:
    # contains always stringifies both sides so numeric cells can be
    # matched by text (GUI search input is always a str).
    assert _values_contains(123, "12") is True
    assert _values_contains("abc", 123) is False
    assert _values_contains(None, "x") is False


# ─── _normalize_conditions ──────────────────────────────────────────────────

def test_normalize_conditions_pair_uses_default() -> None:
    result = _normalize_conditions([("a", "v"), ("b", "w")], "contains")
    assert result == [("a", "v", "contains"), ("b", "w", "contains")]


def test_normalize_conditions_triple_override() -> None:
    result = _normalize_conditions(
        [("a", "v"), ("b", "w", "contains")], "exact"
    )
    assert result == [("a", "v", "exact"), ("b", "w", "contains")]


def test_normalize_conditions_bad_length() -> None:
    with pytest.raises(SearchError, match="must have 2 or 3 elements"):
        _normalize_conditions([("a",)], "exact")


def test_normalize_conditions_bad_mode() -> None:
    with pytest.raises(SearchError, match="invalid mode"):
        _normalize_conditions([("a", "v", "fuzzy")], "exact")


# ─── _match_rows (pure) ────────────────────────────────────────────────────

def _sd(cols, rows) -> SheetData:
    return SheetData(columns=tuple(cols), rows=tuple(rows))


def test_match_rows_exact_first_priority_wins() -> None:
    sd = _sd(["a", "b"], [("x", "y"), ("a_val", "b_val")])
    hits = _match_rows(sd, [("a", "a_val", "exact"), ("b", "b_val", "exact")])
    assert len(hits) == 1
    assert hits[0][1] == 0   # priority 0


def test_match_rows_exact_fallback_to_second() -> None:
    sd = _sd(["a", "b"], [("x", "b_val"), ("y", "b_val")])
    hits = _match_rows(sd, [("a", "a_val", "exact"), ("b", "b_val", "exact")])
    assert len(hits) == 2
    assert all(h[1] == 1 for h in hits)


def test_match_rows_exact_no_match() -> None:
    sd = _sd(["a"], [("nope",)])
    hits = _match_rows(sd, [("a", "a_val", "exact"), ("b", "b_val", "exact")])
    assert hits == []


def test_match_rows_exact_missing_column_skipped() -> None:
    sd = _sd(["b"], [("b_val",)])
    hits = _match_rows(sd, [("a", "a_val", "exact"), ("b", "b_val", "exact")])
    assert len(hits) == 1
    assert hits[0][2] == "b"


def test_match_rows_exact_all_conditions_missing() -> None:
    sd = _sd(["c"], [("c_val",)])
    hits = _match_rows(sd, [("a", "a_val", "exact"), ("b", "b_val", "exact")])
    assert hits == []


def test_match_rows_ragged_row_shorter_than_columns() -> None:
    # Row tuple shorter than columns — out-of-bounds index → None cell.
    sd = SheetData(columns=("a", "b", "c"), rows=(("x",), ("a_val", "y", "z")))
    hits = _match_rows(sd, [("a", "a_val", "exact")])
    assert len(hits) == 1
    assert hits[0][0] == ("a_val", "y", "z")


def test_match_rows_contains_match() -> None:
    sd = _sd(["名称"], [("纯牛奶 250ml",), ("面包 100g",)])
    hits = _match_rows(sd, [("名称", "牛奶", "contains")])
    assert len(hits) == 1
    assert hits[0][0] == ("纯牛奶 250ml",)


def test_match_rows_contains_priority_fallback() -> None:
    sd = _sd(
        ["编码", "名称"],
        [("X999", "纯牛奶"), ("A001", "面包")],
    )
    hits = _match_rows(
        sd,
        [("编码", "A001", "exact"), ("名称", "牛奶", "contains")],
    )
    assert len(hits) == 2
    # ("X999", "纯牛奶"): exact miss on 编码, contains hit on 名称 → priority 1
    # ("A001", "面包"): exact hit on 编码 → priority 0
    assert hits[0] == (("X999", "纯牛奶"), 1, "名称")
    assert hits[1] == (("A001", "面包"), 0, "编码")


def test_match_rows_contains_numeric_coerced() -> None:
    # contains stringifies both sides, so numeric cells can be text-matched.
    sd = _sd(["条码"], [(123,)])
    hits = _match_rows(sd, [("条码", "12", "contains")])
    assert len(hits) == 1
    assert hits[0][0] == (123,)
    assert hits[0][2] == "条码"


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


def test_contains_mode_global(tmp_path: Path) -> None:
    _tmp_xlsx(
        tmp_path, "price.xlsx",
        {"s": (
            ("编码", "名称", "单价"),
            [("A001", "纯牛奶 250ml", 3.5), ("A002", "面包 100g", 2.0)],
        )},
    )
    result = search_files(tmp_path, [("名称", "牛奶")], mode="contains")
    assert len(result.rows) == 1
    assert result.rows[0][2] == "名称"
    name_idx = result.columns.index("名称")
    assert result.rows[0][name_idx] == "纯牛奶 250ml"


def test_contains_per_condition_override(tmp_path: Path) -> None:
    _tmp_xlsx(
        tmp_path, "price.xlsx",
        {"s": (
            ("编码", "名称"),
            [("A001", "面包"), ("X999", "纯牛奶 250ml")],
        )},
    )
    # 编码 uses exact (default), 名称 uses contains (override)
    result = search_files(
        tmp_path,
        [("编码", "A001"), ("名称", "牛奶", "contains")],
        mode="exact",
    )
    assert len(result.rows) == 2
    # ("A001", "面包"): exact hit on 编码 → priority 0
    # ("X999", "纯牛奶 250ml"): exact miss on 编码, contains hit on 名称 → priority 1
    by_field = {r[2]: r[3] for r in result.rows}
    assert by_field["编码"] == 0
    assert by_field["名称"] == 1


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
    _tmp_xlsx(tmp_path, "empty.xlsx", {"空表": (("编码",), [])})
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

    a_row = next(r for r in result.rows if r[0] == "a.xlsx")
    assert a_row[price_idx] == 3.5
    assert a_row[market_idx] is None

    b_row = next(r for r in result.rows if r[0] == "b.xlsx")
    assert b_row[price_idx] is None
    assert b_row[market_idx] == 4.0


def test_result_sorted_by_priority_then_file(tmp_path: Path) -> None:
    _tmp_xlsx(tmp_path, "a.xlsx", {"s": (("编码", "条码"), [("A001", "6901")])})
    _tmp_xlsx(tmp_path, "b.xlsx", {"s": (("编码", "条码"), [("X999", "6901")])})

    result = search_files(tmp_path, [("编码", "A001"), ("条码", "6901")])
    files = [r[0] for r in result.rows]
    assert files[0] == "a.xlsx"
    assert files[1] == "b.xlsx"


def test_no_match_returns_empty(tmp_path: Path) -> None:
    _tmp_xlsx(tmp_path, "price.xlsx", {"s": (("编码",), [("A001",)])})
    result = search_files(tmp_path, [("编码", "NOTEXIST")])
    assert result.rows == ()
    assert "__file__" in result.columns


def test_no_match_empty_includes_columns(tmp_path: Path) -> None:
    _tmp_xlsx(
        tmp_path, "price.xlsx",
        {"s": (("编码", "单价"), [("A001", 3.5)])},
    )
    result = search_files(tmp_path, [("编码", "NOTEXIST")])
    assert "编码" in result.columns
    assert "单价" in result.columns


def test_ignores_non_xlsx(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("ignore me")
    _tmp_xlsx(tmp_path, "price.xlsx", {"s": (("编码",), [("A001",)])})
    result = search_files(tmp_path, [("编码", "A001")])
    assert len(result.rows) == 1


def test_mode_invalid() -> None:
    with pytest.raises(SearchError, match="invalid mode"):
        search_files(Path("."), [("a", "v")], mode="fuzzy")  # type: ignore[arg-type]


# ─── Error paths ────────────────────────────────────────────────────────────

def test_directory_not_found() -> None:
    with pytest.raises(SearchError, match="does not exist"):
        search_files("/nonexistent/path/xyz", [("编码", "A001")])


def test_empty_conditions() -> None:
    with pytest.raises(SearchError, match="must not be empty"):
        search_files(Path("."), [])


def test_invalid_field_name(tmp_path: Path) -> None:
    with pytest.raises(SearchError, match="invalid field name"):
        search_files(tmp_path, [("", "value")])


def test_whitespace_field_name_rejected(tmp_path: Path) -> None:
    with pytest.raises(SearchError, match="invalid field name"):
        search_files(tmp_path, [("   ", "value")])


def test_no_xlsx_files(tmp_path: Path) -> None:
    (tmp_path / "readme.md").write_text("hi")
    with pytest.raises(SearchError, match="no .xlsx files"):
        search_files(tmp_path, [("编码", "A001")])


# ─── search_error hierarchy ─────────────────────────────────────────────────

def test_search_error_is_excelops_error() -> None:
    from excelops import ExcelOpsError
    assert issubclass(SearchError, ExcelOpsError)