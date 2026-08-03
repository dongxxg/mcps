"""``derive`` primitive — add a computed column.

Pure function: applies ``fn`` to each row (as a ``dict[str, Any]`` of
column-name -> value) and appends the result as a new column. The input is never
mutated.
"""

from __future__ import annotations

from ..backends.models import SheetData

__all__ = ["derive"]


def derive(
    sd: SheetData,
    name: str,
    fn: object,
) -> SheetData:
    """Add a computed column ``name`` whose value is ``fn(row_dict)``.

    Args:
        sd: Source data.
        name: Name of the new column appended after existing columns.
        fn: Callable receiving ``dict[str, Any]`` (column-name -> value for one
            row) and returning the new column's value for that row.

    Returns:
        A new ``SheetData`` with the appended computed column.

    Raises:
        ValueError: If ``name`` already exists in ``sd.columns``.
    """
    if name in sd.columns:
        raise ValueError(f"column {name!r} already exists")

    columns = sd.columns + (name,)
    rows = tuple(
        row + (fn(dict(zip(sd.columns, row, strict=True))),)
        for row in sd.rows
    )
    return SheetData(columns=columns, rows=rows)
