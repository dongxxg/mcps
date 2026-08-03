"""Tests for ``ops.project`` — select + reorder + rename columns."""

from __future__ import annotations

import pytest

from excelops.backends.models import SheetData
from excelops.errors import ProjectError
from excelops.ops import project


def test_select_columns(abcd_sheet: SheetData) -> None:
    result = project(abcd_sheet, columns=["b", "d"])
    assert result.columns == ("b", "d")
    assert result.rows == ((2, 4), (6, 8))


def test_reorder_columns(abcd_sheet: SheetData) -> None:
    result = project(abcd_sheet, columns=["c", "a", "b"])
    assert result.columns == ("c", "a", "b")
    assert result.rows == ((3, 1, 2), (7, 5, 6))


def test_rename_columns(abcd_sheet: SheetData) -> None:
    result = project(abcd_sheet, columns=["a", "b"], rename={"b": "B列"})
    assert result.columns == ("a", "B列")
    assert result.rows == ((1, 2), (5, 6))


def test_column_not_found_raises(abcd_sheet: SheetData) -> None:
    with pytest.raises(ProjectError) as exc_info:
        project(abcd_sheet, columns=["a", "not_exist"])
    assert "not_exist" in str(exc_info.value)


def test_does_not_mutate_input(abcd_sheet: SheetData) -> None:
    original_columns = abcd_sheet.columns
    original_rows = abcd_sheet.rows
    project(abcd_sheet, columns=["a"])
    assert abcd_sheet.columns is original_columns
    assert abcd_sheet.rows is original_rows


def test_chinese_column_names(chinese_sheet: SheetData) -> None:
    result = project(chinese_sheet, columns=["名称", "单价"], rename={"单价": "价格"})
    assert result.columns == ("名称", "价格")
    assert result.rows == (("纯牛奶", 3.5), ("面包", 2.0))
