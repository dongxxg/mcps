"""``filter`` primitive — keep rows matching a predicate.

Pure function: keeps only rows for which ``predicate(row_dict)`` returns
``True``. The input is never mutated.
"""

from __future__ import annotations

from ..backends.models import SheetData

__all__ = ["filter"]


def filter(
    sd: SheetData,
    predicate: object,
) -> SheetData:
    """Keep rows where ``predicate(dict)`` is ``True``.

    Args:
        sd: Source data.
        predicate: Callable receiving ``dict[str, Any]`` (column-name -> value)
            and returning ``bool``.

    Returns:
        A new ``SheetData`` with only the matching rows (columns unchanged).
    """
    rows = tuple(
        row for row in sd.rows if predicate(dict(zip(sd.columns, row, strict=True)))
    )
    return SheetData(columns=sd.columns, rows=rows)
