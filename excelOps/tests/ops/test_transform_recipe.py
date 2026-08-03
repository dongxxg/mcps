"""Tests for ``ops.transform_tables`` recipe."""

from __future__ import annotations

from excelops.backends.models import SheetData
from excelops.ops import transform_tables


def test_map_rule() -> None:
    sd = SheetData(columns=("a", "b"), rows=((1, 2), (3, 4)))
    result = transform_tables(
        {"t": sd},
        [{"kind": "map", "source": "a", "target": "alpha"}],
    )
    assert "alpha" in result.columns


def test_expr_rule() -> None:
    sd = SheetData(columns=("a", "b"), rows=((1, 2), (3, 4)))
    result = transform_tables(
        {"t": sd},
        [{"kind": "expr", "target": "sum", "expr": "a + b"}],
    )
    assert result.columns[-1] == "sum"
    assert result.rows == ((1, 2, 3), (3, 4, 7))


def test_factor_rule() -> None:
    sd = SheetData(columns=("箱数",), rows=((10,), (20,)))
    result = transform_tables(
        {"t": sd},
        [{"kind": "factor", "source": "箱数", "target": "瓶数", "factor": 12}],
    )
    assert result.rows == ((10, 120.0), (20, 240.0))


def test_when_rule() -> None:
    sd = SheetData(columns=("库存",), rows=((5,), (50,)))
    result = transform_tables(
        {"t": sd},
        [{"kind": "when", "target": "补货", "condition": "库存 < 10", "then": "是", "else": "否"}],
    )
    assert result.rows == ((5, "是"), (50, "否"))
