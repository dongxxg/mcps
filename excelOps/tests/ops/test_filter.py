"""Tests for ``ops.filter`` — keep rows matching ``predicate(dict) -> bool``."""

from __future__ import annotations

import pytest

from excelops.backends.models import SheetData
from excelops.ops import filter as filter_rows


def test_basic_filter(abcd_sheet: SheetData) -> None:
    result = filter_rows(abcd_sheet, lambda r: r["a"] > 1)
    assert result.columns == ("a", "b", "c", "d")
    assert result.rows == ((5, 6, 7, 8),)


def test_predicate_receives_dict(abcd_sheet: SheetData) -> None:
    captured: list[dict] = []

    def capture(r: dict) -> bool:
        captured.append(r)
        return True

    filter_rows(abcd_sheet, capture)
    assert captured == [
        {"a": 1, "b": 2, "c": 3, "d": 4},
        {"a": 5, "b": 6, "c": 7, "d": 8},
    ]


def test_all_match(abcd_sheet: SheetData) -> None:
    result = filter_rows(abcd_sheet, lambda r: True)
    assert result.rows == abcd_sheet.rows


def test_none_match(abcd_sheet: SheetData) -> None:
    result = filter_rows(abcd_sheet, lambda r: False)
    assert result.columns == abcd_sheet.columns
    assert result.rows == ()


def test_does_not_mutate_input(abcd_sheet: SheetData) -> None:
    original_rows = abcd_sheet.rows
    filter_rows(abcd_sheet, lambda r: r["a"] > 100)
    assert abcd_sheet.rows is original_rows
