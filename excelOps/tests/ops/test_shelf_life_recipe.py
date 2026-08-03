"""Tests for ``ops.calc_shelf_life`` recipe."""

from __future__ import annotations

from datetime import date
from fractions import Fraction

import pytest

from excelops.backends.models import SheetData
from excelops.errors import TransformError
from excelops.ops import calc_shelf_life


def _make_sheet(rows) -> SheetData:
    return SheetData(
        columns=("生产日期", "保质期"),
        rows=rows,
    )


def test_days_unit_not_expired() -> None:
    sd = _make_sheet(((date(2026, 1, 1), "365天"),))
    result = calc_shelf_life(
        sd, "生产日期", "保质期",
        fraction=Fraction(1, 3),
        reference_date=date(2026, 3, 1),
    )
    assert result.rows[0][-1] is False


def test_days_unit_expired() -> None:
    sd = _make_sheet(((date(2026, 1, 1), "365天"),))
    result = calc_shelf_life(
        sd, "生产日期", "保质期",
        fraction=Fraction(1, 2),
        reference_date=date(2026, 8, 1),
    )
    assert result.rows[0][-1] is True


def test_months_unit() -> None:
    sd = _make_sheet(((date(2026, 1, 15), "6个月"),))
    result = calc_shelf_life(
        sd, "生产日期", "保质期",
        fraction=Fraction(1, 2),
        reference_date=date(2026, 5, 1),
    )
    # 3-month threshold = 2026-04-15, ref 2026-05-01 is past
    assert result.rows[0][-1] is True


def test_years_unit() -> None:
    sd = _make_sheet(((date(2024, 6, 1), "2年"),))
    result = calc_shelf_life(
        sd, "生产日期", "保质期",
        fraction=Fraction(1, 2),
        reference_date=date(2025, 7, 1),
    )
    # 1-year threshold = 2025-06-01, ref 2025-07-01 is past
    assert result.rows[0][-1] is True


def test_bare_number_defaults_to_days() -> None:
    sd = _make_sheet(((date(2026, 1, 1), "180"),))
    result = calc_shelf_life(
        sd, "生产日期", "保质期",
        fraction=Fraction(1, 2),
        reference_date=date(2026, 5, 1),
    )
    # 90-day threshold = 2026-03-31, ref 2026-05-01 is past
    assert result.rows[0][-1] is True


def test_unparseable_raises() -> None:
    sd = _make_sheet(((date(2026, 1, 1), "半年"),))
    with pytest.raises(TransformError):
        calc_shelf_life(sd, "生产日期", "保质期")


def test_none_produces_none() -> None:
    sd = _make_sheet(((None, "180天"),))
    result = calc_shelf_life(sd, "生产日期", "保质期")
    assert result.rows[0][-1] is None
