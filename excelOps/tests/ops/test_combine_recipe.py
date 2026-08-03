"""Tests for ``ops.combine_reports`` recipe."""

from __future__ import annotations

from excelops.ops import combine_reports


def test_combine_same_format(report_a, report_b) -> None:
    result = combine_reports([report_a, report_b])
    assert "地区" in result.columns
    assert "产品" in result.columns
    assert "金额" in result.columns
    assert len(result.rows) == 4  # 2 + 2


def test_combine_with_column_order(report_a, report_b) -> None:
    result = combine_reports([report_a, report_b], column_order=["地区", "金额"])
    assert result.columns == ("地区", "金额")
    assert len(result.rows) == 4
