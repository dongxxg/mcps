"""``lookup`` primitive — priority key fallback + column fetch.

Pure function: for each row in ``source``, tries to find a matching row in
``table`` by a priority-ordered list of key pairs. The first key pair that
matches wins; if none match, the ``on_missing`` strategy applies. Matched rows
contribute the requested ``fetch`` columns, appended to the source.

Performance: builds a ``dict[value -> row]`` index per key column up front, so
lookup is O(n + m) rather than O(n * m). Duplicate keys resolve to the first
row (deterministic).
"""

from __future__ import annotations

from ..backends.models import SheetData
from ..errors import LookupError

__all__ = ["lookup"]

_MARK = "__未找到__"


def lookup(
    source: SheetData,
    table: SheetData,
    on: list[tuple[str, str]],
    fetch: list[str],
    on_missing: str = "mark",
) -> SheetData:
    """Priority key fallback lookup with column fetch.

    Args:
        source: Rows to look up from.
        table: Reference table to search.
        on: Ordered list of ``(source_col, table_col)`` key pairs, in priority
            order. The first pair that produces a match wins.
        fetch: Column names from ``table`` to append to each source row on a
            match.
        on_missing: Strategy when no key matches a row — ``"mark"`` (fill with
            ``"__未找到__"``), ``"null"`` (fill with ``None``), or ``"error"``
            (raise ``LookupError``).

    Returns:
        A new ``SheetData`` with the ``fetch`` columns appended.

    Raises:
        LookupError: If ``on_missing="error"`` and a row has no match, or if
            a key column is missing from ``source``/``table``.
        ValueError: If ``on_missing`` is not one of the allowed strategies.
    """
    if on_missing not in ("mark", "null", "error"):
        raise ValueError(f"invalid on_missing={on_missing!r}")

    # Keep only key pairs where both sides exist. This lets a default key list
    # like 编码→条码→名称 gracefully degrade when the source lacks some columns.
    valid_on = [
        (src_col, tbl_col) for src_col, tbl_col in on
        if src_col in source.columns and tbl_col in table.columns
    ]
    if not valid_on:
        raise LookupError(
            f"no valid key pairs from {on!r}; "
            f"source columns: {list(source.columns)}, "
            f"table columns: {list(table.columns)}"
        )

    # Validate fetch columns exist in table.
    for col in fetch:
        if col not in table.columns:
            raise LookupError(f"fetch column {col!r} not in table")

    # Pre-build one index per (table_col) -> first row index.
    # Only build the indexes we actually need (the table-side key columns).
    tbl_index = {name: i for i, name in enumerate(table.columns)}
    indexes: dict[str, dict[object, int]] = {}
    for _, tbl_col in valid_on:
        if tbl_col not in indexes:
            idx: dict[object, int] = {}
            col_i = tbl_index[tbl_col]
            for row_i, row in enumerate(table.rows):
                key = row[col_i] if col_i < len(row) else None
                if key is not None and key not in idx:
                    idx[key] = row_i
            indexes[tbl_col] = idx

    src_index = {name: i for i, name in enumerate(source.columns)}
    fetch_indexes = [tbl_index[c] for c in fetch]

    out_columns = source.columns + tuple(fetch)
    out_rows: list[tuple] = []

    for row in source.rows:
        matched_row: tuple | None = None
        for src_col, tbl_col in valid_on:
            src_i = src_index[src_col]
            val = row[src_i] if src_i < len(row) else None
            if val is None:
                continue
            hit = indexes[tbl_col].get(val)
            if hit is not None:
                matched_row = table.rows[hit]
                break

        if matched_row is not None:
            fetched = tuple(
                matched_row[i] if i < len(matched_row) else None
                for i in fetch_indexes
            )
        elif on_missing == "null":
            fetched = (None,) * len(fetch)
        elif on_missing == "error":
            raise LookupError(
                f"no match for source row {row!r} on keys {on}"
            )
        else:  # mark
            fetched = (_MARK,) * len(fetch)

        out_rows.append(row + fetched)

    return SheetData(columns=out_columns, rows=tuple(out_rows))
