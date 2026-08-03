"""Tests for ``ops.lookup`` — priority key fallback + column fetch."""

from __future__ import annotations

import pytest

from excelops.backends.models import SheetData
from excelops.errors import LookupError
from excelops.ops import lookup


def _price_table() -> SheetData:
    return SheetData(
        columns=("编码", "条码", "名称", "单价", "税率"),
        rows=(
            ("A001", "6901234", "纯牛奶 250ml", 3.5, 0.13),
            ("A002", "6905678", "面包 100g", 2.0, 0.09),
        ),
    )


def _source() -> SheetData:
    return SheetData(
        columns=("编码", "条码", "名称", "数量"),
        rows=(
            ("A001", "6901234", "纯牛奶", 10),   # code matches
            ("X999", "6905678", "面包", 20),    # barcode matches
            ("X999", "X000000", "面包 100g", 5),  # name matches
            ("X999", "X000000", "不存在", 1),   # no match
        ),
    )


def test_single_key_match() -> None:
    src = SheetData(columns=("编码",), rows=(("A001",),))
    result = lookup(src, _price_table(), on=[("编码", "编码")], fetch=["单价"])
    assert result.columns == ("编码", "单价")
    assert result.rows == (("A001", 3.5),)


def test_priority_fallback() -> None:
    result = lookup(
        _source(), _price_table(),
        on=[("编码", "编码"), ("条码", "条码"), ("名称", "名称")],
        fetch=["单价"],
    )
    # Source cols (编码,条码,名称,数量) + fetch (单价) = 5 cols.
    # A001 via code, X999/6905678 via barcode, X999/面包 100g via name, 不存在→mark
    assert result.columns == ("编码", "条码", "名称", "数量", "单价")
    assert result.rows[0] == ("A001", "6901234", "纯牛奶", 10, 3.5)
    assert result.rows[1] == ("X999", "6905678", "面包", 20, 2.0)
    assert result.rows[2] == ("X999", "X000000", "面包 100g", 5, 2.0)
    assert result.rows[3] == ("X999", "X000000", "不存在", 1, "__未找到__")


def test_on_missing_mark_default() -> None:
    src = SheetData(columns=("编码",), rows=(("NOPE",),))
    result = lookup(src, _price_table(), on=[("编码", "编码")], fetch=["单价"])
    assert result.rows == (("NOPE", "__未找到__"),)


def test_on_missing_null() -> None:
    src = SheetData(columns=("编码",), rows=(("NOPE",),))
    result = lookup(
        src, _price_table(),
        on=[("编码", "编码")], fetch=["单价"], on_missing="null",
    )
    assert result.rows == (("NOPE", None),)


def test_on_missing_error() -> None:
    src = SheetData(columns=("编码",), rows=(("NOPE",),))
    with pytest.raises(LookupError) as exc_info:
        lookup(
            src, _price_table(),
            on=[("编码", "编码")], fetch=["单价"], on_missing="error",
        )
    assert "NOPE" in str(exc_info.value)


def test_duplicate_key_takes_first() -> None:
    table = SheetData(
        columns=("编码", "单价"),
        rows=(("A001", 3.5), ("A001", 9.9)),
    )
    src = SheetData(columns=("编码",), rows=(("A001",),))
    result = lookup(src, table, on=[("编码", "编码")], fetch=["单价"])
    assert result.rows == (("A001", 3.5),)


def test_fetch_multiple_columns() -> None:
    src = SheetData(columns=("编码",), rows=(("A001",),))
    result = lookup(
        src, _price_table(),
        on=[("编码", "编码")], fetch=["单价", "税率"],
    )
    assert result.columns == ("编码", "单价", "税率")
    assert result.rows == (("A001", 3.5, 0.13),)


def test_does_not_mutate_input() -> None:
    src = SheetData(columns=("编码",), rows=(("A001",),))
    original = src.rows
    lookup(src, _price_table(), on=[("编码", "编码")], fetch=["单价"])
    assert src.rows is original


def test_none_source_value_skips_key() -> None:
    """A None value in the source column must not match anything."""
    table = SheetData(
        columns=("编码", "单价"),
        rows=(("A001", 3.5),),
    )
    src = SheetData(columns=("编码",), rows=((None,),))
    result = lookup(src, table, on=[("编码", "编码")], fetch=["单价"])
    assert result.rows == ((None, "__未找到__"),)
