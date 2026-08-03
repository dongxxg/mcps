"""Pure-memory fixtures for ops tests — no xlsx I/O, milliseconds per test."""

from __future__ import annotations

from datetime import date

import pytest

from excelops.backends.models import SheetData


@pytest.fixture
def abcd_sheet() -> SheetData:
    """Columns [a, b, c, d] with 2 data rows."""
    return SheetData(
        columns=("a", "b", "c", "d"),
        rows=((1, 2, 3, 4), (5, 6, 7, 8)),
    )


@pytest.fixture
def chinese_sheet() -> SheetData:
    """Columns with Chinese names: [编码, 名称, 单价, 数量]."""
    return SheetData(
        columns=("编码", "名称", "单价", "数量"),
        rows=(
            ("A001", "纯牛奶", 3.5, 10),
            ("A002", "面包", 2.0, 20),
        ),
    )


@pytest.fixture
def price_table() -> SheetData:
    """Price lookup table: [编码, 条码, 名称, 单价, 税率]."""
    return SheetData(
        columns=("编码", "条码", "名称", "单价", "税率"),
        rows=(
            ("A001", "6901234", "纯牛奶 250ml", 3.5, 0.13),
            ("A002", "6905678", "面包 100g", 2.0, 0.09),
            ("A003", "6909999", "矿泉水 500ml", 1.5, 0.13),
        ),
    )


@pytest.fixture
def sales_sheet() -> SheetData:
    """Sales sheet with a date column: [日期, 编码, 数量]."""
    return SheetData(
        columns=("日期", "编码", "数量"),
        rows=(
            (date(2026, 1, 1), "A001", 10),
            (date(2026, 1, 2), "A002", 20),
            (date(2026, 1, 3), "A999", 5),
        ),
    )


@pytest.fixture
def report_a() -> SheetData:
    """Report A: columns [地区, 产品, 金额]."""
    return SheetData(
        columns=("地区", "产品", "金额"),
        rows=(("华东", "牛奶", 100), ("华北", "面包", 200)),
    )


@pytest.fixture
def report_b() -> SheetData:
    """Report B: columns [产品, 地区, 金额, 数量] (different order + extra col)."""
    return SheetData(
        columns=("产品", "地区", "金额", "数量"),
        rows=(("牛奶", "华东", 150, 10), ("面包", "华南", 250, 20)),
    )


@pytest.fixture
def report_c() -> SheetData:
    """Report C: columns [金额, 地区] (subset)."""
    return SheetData(
        columns=("金额", "地区"),
        rows=((300, "西南"),),
    )
