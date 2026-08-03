"""Tests for ``ops.narrate`` — template text rendering."""

from __future__ import annotations

import pytest

from excelops.backends.models import SheetData
from excelops.ops import narrate


def test_single_placeholder() -> None:
    assert narrate({"总金额": 1500}, "总金额{总金额}元") == "总金额1500元"


def test_multiple_placeholders() -> None:
    assert (
        narrate({"地区": "华东", "数量": 42, "金额": 3200}, "{地区}地区共{数量}件，合计{金额}元")
        == "华东地区共42件，合计3200元"
    )


def test_decimal_format() -> None:
    assert narrate({"单价": 3.5}, "单价{单价:.2f}元") == "单价3.50元"


def test_thousands_separator() -> None:
    assert narrate({"总额": 1234567}, "总额{总额:,}元") == "总额1,234,567元"


def test_missing_key_keeps_placeholder() -> None:
    assert narrate({"A": 1}, "{A}和{B}") == "1和{B}"


def test_no_placeholder() -> None:
    assert narrate({}, "核算完成") == "核算完成"


def test_batch_render() -> None:
    sd = SheetData(
        columns=("地区", "数量"),
        rows=(("华东", 42), ("华北", 18)),
    )
    result = narrate(sd, "{地区}: {数量}件")
    assert result == ["华东: 42件", "华北: 18件"]
