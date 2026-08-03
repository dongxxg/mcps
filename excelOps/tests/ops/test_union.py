"""Tests for ``ops.union`` — vertical stack with column-name alignment."""

from __future__ import annotations

import pytest

from excelops.backends.models import SheetData
from excelops.errors import CombineError
from excelops.ops import union


def test_homogeneous_stack() -> None:
    a = SheetData(columns=("x", "y"), rows=((1, 2), (3, 4)))
    b = SheetData(columns=("x", "y"), rows=((5, 6),))
    result = union([a, b])
    assert result.columns == ("x", "y")
    assert result.rows == ((1, 2), (3, 4), (5, 6))


def test_intersection_alignment() -> None:
    a = SheetData(columns=("a", "b", "c"), rows=((1, 2, 3),))
    b = SheetData(columns=("b", "c", "d"), rows=((4, 5, 6),))
    result = union([a, b])
    assert result.columns == ("a", "b", "c", "d")
    assert result.rows == ((1, 2, 3, None), (None, 4, 5, 6))


def test_disjoint_columns() -> None:
    a = SheetData(columns=("a", "b"), rows=((1, 2),))
    b = SheetData(columns=("c", "d"), rows=((3, 4),))
    result = union([a, b])
    assert result.columns == ("a", "b", "c", "d")
    assert result.rows == ((1, 2, None, None), (None, None, 3, 4))


def test_column_order() -> None:
    a = SheetData(columns=("a", "b", "c", "d"), rows=((1, 2, 3, 4),))
    result = union([a], column_order=["c", "a", "d"])
    assert result.columns == ("c", "a", "d")
    assert result.rows == ((3, 1, 4),)


def test_column_order_drops_columns() -> None:
    a = SheetData(columns=("a", "b", "c"), rows=((1, 2, 3),))
    result = union([a], column_order=["a", "c"])
    assert result.columns == ("a", "c")
    assert result.rows == ((1, 3),)


def test_column_order_unknown_raises() -> None:
    a = SheetData(columns=("a", "b"), rows=((1, 2),))
    with pytest.raises(CombineError):
        union([a], column_order=["a", "not_exist"])


def test_empty_input_raises() -> None:
    with pytest.raises(CombineError):
        union([])


def test_single_table() -> None:
    a = SheetData(columns=("x", "y"), rows=((1, 2), (3, 4)))
    result = union([a])
    assert result.columns == ("x", "y")
    assert result.rows == ((1, 2), (3, 4))


def test_does_not_mutate_input() -> None:
    a = SheetData(columns=("a", "b"), rows=((1, 2),))
    b = SheetData(columns=("a", "b", "c"), rows=((3, 4, 5),))
    original_rows_a = a.rows
    original_rows_b = b.rows
    union([a, b])
    assert a.rows is original_rows_a
    assert b.rows is original_rows_b


def test_three_tables() -> None:
    a = SheetData(columns=("x",), rows=((1,),))
    b = SheetData(columns=("x", "y"), rows=((2, 3),))
    c = SheetData(columns=("x",), rows=((4,),))
    result = union([a, b, c])
    assert result.columns == ("x", "y")
    assert result.rows == ((1, None), (2, 3), (4, None))
