"""``project`` primitive — select + reorder + rename columns.

Pure function: consumes a ``SheetData`` and returns a new ``SheetData`` containing
only the requested columns, in the requested order, optionally renamed. The input
is never mutated.
"""

from __future__ import annotations

from ..backends.models import SheetData
from ..errors import ProjectError

__all__ = ["project"]


def project(
    sd: SheetData,
    columns: list[str],
    rename: dict[str, str] | None = None,
) -> SheetData:
    """Select, reorder, and optionally rename columns.

    Args:
        d: Source data.
        columns: Desired column names in output order. Every name MUST exist in
            ``sd.columns`` or ``ProjectError`` is raised.
        rename: Optional mapping ``{original_name: new_name}`` applied after
            selection. Keys must be a subset of ``columns``.

    Returns:
        A new ``SheetData`` with the projected columns.

    Raises:
        ProjectError: If a name in ``columns`` is not in ``sd.columns``.
    """
    # Validate all requested columns exist up front — fail fast, before
    # constructing anything, so a bad call leaves no half-built state.
    index = {name: i for i, name in enumerate(sd.columns)}
    missing = [c for c in columns if c not in index]
    if missing:
        raise ProjectError(
            f"column(s) not found: {missing}; available: {list(sd.columns)}"
        )

    rename = rename or {}
    out_columns = tuple(rename.get(c, c) for c in columns)
    out_rows = tuple(
        tuple(row[index[c]] for c in columns) for row in sd.rows
    )
    return SheetData(columns=out_columns, rows=out_rows)
