"""``calc_shelf_life`` recipe — configurable shelf-life fraction check."""

from __future__ import annotations

import re
from datetime import date, timedelta
from fractions import Fraction

from ..backends.models import SheetData
from ..errors import TransformError
from .derive import derive

__all__ = ["calc_shelf_life"]

# Matches "180天", "12个月", "2年", "180" (bare number -> days).
_SHELF_LIFE_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*(天|日|个月?|年)?$")

_MONTHS_PER_YEAR = 12


def _parse_shelf_life(value: object) -> tuple[float, str]:
    """Parse a shelf-life string into (number, unit). Unit: 'day'/'month'/'year'."""
    if value is None or value == "":
        return (0, "day")
    s = str(value).strip()
    m = _SHELF_LIFE_RE.match(s)
    if not m:
        raise TransformError(f"unparseable shelf-life value: {value!r}")
    num = float(m.group(1))
    unit_raw = m.group(2)
    if unit_raw is None or unit_raw in ("天", "日"):
        unit = "day"
    elif unit_raw in ("月", "个月"):
        unit = "month"
    elif unit_raw == "年":
        unit = "year"
    else:
        unit = "day"
    return (num, unit)


def _add_duration(start: date, num: float, unit: str) -> date:
    """Add a duration to a date, handling month/year rollover without dateutil."""
    if unit == "day":
        return start + timedelta(days=num)
    months = num * _MONTHS_PER_YEAR if unit == "year" else num
    total_months = start.month + int(months)
    year = start.year + (total_months - 1) // _MONTHS_PER_YEAR
    month = (total_months - 1) % _MONTHS_PER_YEAR + 1
    day = min(start.day, _days_in_month(year, month))
    return date(year, month, day)


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - date(year, month, 1)).days


def calc_shelf_life(
    sd: SheetData,
    production_col: str,
    shelf_life_col: str,
    fraction: Fraction = Fraction(1, 3),
    reference_date: date | None = None,
    output_col: str = "是否超保",
) -> SheetData:
    """Add a boolean column indicating whether each row has passed ``fraction``
    of its shelf life.

    Args:
        sd: Source data.
        production_col: Column holding the production date.
        shelf_life_col: Column holding shelf-life as a string (e.g. "180天",
            "12个月", "2年", or a bare number for days).
        fraction: Threshold fraction of shelf life (default 1/3).
        reference_date: Date to evaluate against (default ``date.today()``).
        output_col: Name of the appended boolean column.
    """
    ref = reference_date or date.today()

    def _eval(row: dict) -> bool | None:
        prod = row[production_col]
        shelf_raw = row[shelf_life_col]
        if prod is None or shelf_raw is None or shelf_raw == "":
            return None
        if not isinstance(prod, date):
            raise TransformError(
                f"production date must be a date, got {type(prod).__name__}: {prod!r}"
            )
        num, unit = _parse_shelf_life(shelf_raw)
        threshold_date = _add_duration(prod, num * float(fraction), unit)
        return ref >= threshold_date

    return derive(sd, output_col, _eval)
