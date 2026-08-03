"""``union`` primitive — vertical stack with column-name alignment.

Pure function: stacks multiple ``SheetData`` rows, aligning by column name.
Columns present in some tables but not others are filled with ``None``. The
inputs are never mutated.

This is the single source of truth for column alignment in excelops — the
``backends.merger`` is expected to call this for its data layer (Phase 2).
"""

from __future__ import annotations

from ..backends.models import SheetData
from ..errors import CombineError

__all__ = ["union"]


def union(
    tables: list[SheetData],
    column_order: list[str] | None = None,
) -> SheetData:
    """Stack ``tables`` vertically, aligning by column name.

    Args:
        tables: Non-empty list of ``SheetData`` to stack.
        column_order: Optional output column order. If ``None``, uses the first
            table's column order, then appends any new columns from subsequent
            tables in encounter order. If given, every name MUST exist in the
            union of all table columns.

    Returns:
        A new ``SheetData`` with all rows and the aligned columns.

    Raises:
        CombineError: If ``tables`` is empty, or ``column_order`` references
            a column not present in any table.
    """
    if not tables:
        raise CombineError("union requires at least one table")

    # --- compute the full column union (first-table order, then new cols) ---
    merged: list[str] = []
    seen: set[str] = set()
    for t in tables:
        for name in t.columns:
            if name not in seen:
                merged.append(name)
                seen.add(name)

    # --- resolve final output column order ---
    if column_order is not None:
        missing = [c for c in column_order if c not in seen]
        if missing:
            raise CombineError(
                f"column_order references unknown column(s): {missing}; "
                f"available: {merged}"
            )
        out_columns = tuple(column_order)
    else:
        out_columns = tuple(merged)

    out_index = {name: i for i, name in enumerate(out_columns)}

    # --- remap each table's rows into the output column order ---
    out_rows: list[tuple] = []
    for t in tables:
        t_index = {name: i for i, name in enumerate(t.columns)}
        for row in t.rows:
            new_row = [None] * len(out_columns)
            for name, i in t_index.items():
                if name in out_index:
                    new_row[out_index[name]] = row[i] if i < len(row) else None
            out_rows.append(tuple(new_row))

    return SheetData(columns=out_columns, rows=tuple(out_rows))
