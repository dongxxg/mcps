"""Tests for ``ops.derive`` — add a computed column via ``fn(dict) -> value``."""

from __future__ import annotations

import pytest

from excelops.backends.models import SheetData
from excelops.ops import derive


def test_basic_derive(abcd_sheet: SheetData) -> None:
    result = derive(abcd_sheet, "sum_ab", lambda r: r["a"] + r["b"])
    assert result.columns == ("a", "b", "c", "d", "sum_ab")
    assert result.rows == ((1, 2, 3, 4, 3), (5, 6, 7, 8, 11))


def test_fn_receives_dict_with_column_names(abcd_sheet: SheetData) -> None:
    captured: list[dict] = []

    def capture(r: dict) -> None:
        captured.append(r)

    derive(abcd_sheet, "x", capture)
    assert captured == [
        {"a": 1, "b": 2, "c": 3, "d": 4},
        {"a": 5, "b": 6, "c": 7, "d": 8},
    ]


def test_chinese_column_names(chinese_sheet: SheetData) -> None:
    result = derive(chinese_sheet, "总价", lambda r: r["单价"] * r["数量"])
    assert result.columns == ("编码", "名称", "单价", "数量", "总价")
    assert result.rows == (("A001", "纯牛奶", 3.5, 10, 35.0), ("A002", "面包", 2.0, 20, 40.0))


def test_none_propagation(abcd_sheet: SheetData) -> None:
    sheet = SheetData(
        columns=("a", "b"),
        rows=((1, None), (None, 3)),
    )
    result = derive(sheet, "total", lambda r: (r["a"] or 0) + (r["b"] or 0))
    assert result.rows == ((1, None, 1), (None, 3, 3))


def test_does_not_mutate_input(abcd_sheet: SheetData) -> None:
    original = abcd_sheet
    derive(abcd_sheet, "x", lambda r: 0)
    assert abcd_sheet is original
    assert abcd_sheet.columns == ("a", "b", "c", "d")
