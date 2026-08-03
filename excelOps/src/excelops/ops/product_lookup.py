"""``lookup_product`` recipe — code → barcode → name fallback price lookup."""

from __future__ import annotations

from ..backends.models import SheetData
from .lookup import lookup

__all__ = ["lookup_product"]


def lookup_product(
    source: SheetData,
    price_table: SheetData,
    keys: list[tuple[str, str]] | None = None,
    fetch: list[str] = ("单价",),
    on_missing: str = "mark",
) -> SheetData:
    """Look up product info from a price table with multi-level key fallback.

    Default priority: 编码 → 条码 → 商品名称. Pass ``keys`` to customize the
    ``[(source_col, table_col), ...]`` priority list.

    Args:
        source: Rows to look up from.
        price_table: Reference price table.
        keys: Priority-ordered ``(source_col, table_col)`` pairs. Defaults to
            ``[("编码", "编码"), ("条码", "条码"), ("名称", "名称")]``.
        fetch: Columns to fetch from the price table.
        on_missing: ``"mark"`` / ``"null"`` / ``"error"`` strategy.
    """
    if keys is None:
        keys = [("编码", "编码"), ("条码", "条码"), ("名称", "名称")]
    return lookup(source, price_table, on=keys, fetch=list(fetch), on_missing=on_missing)
