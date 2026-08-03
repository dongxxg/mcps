"""Tests for ``ops.lookup_product`` recipe."""

from __future__ import annotations

from datetime import date

from excelops.ops import lookup_product


def test_code_match(price_table, sales_sheet) -> None:
    result = lookup_product(
        sales_sheet, price_table,
        fetch=["单价"], on_missing="mark",
    )
    assert result.columns == ("日期", "编码", "数量", "单价")
    assert result.rows[0] == (date(2026, 1, 1), "A001", 10, 3.5)  # code match


def test_no_match_marked(price_table) -> None:
    src = SheetData(columns=("编码",), rows=(("NOPE",),))
    result = lookup_product(src, price_table, fetch=["单价"], on_missing="mark")
    assert result.rows == (("NOPE", "__未找到__"),)


# Reuse SheetData import.
from excelops.backends.models import SheetData  # noqa: E402
