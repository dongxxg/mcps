"""``combine_reports`` recipe — merge multiple similar reports."""

from __future__ import annotations

from ..backends.models import SheetData
from .project import project
from .union import union

__all__ = ["combine_reports"]


def combine_reports(
    reports: list[SheetData],
    column_order: list[str] | None = None,
) -> SheetData:
    """Stack multiple similar reports vertically, aligning by column name.

    Args:
        reports: Non-empty list of report tables. Columns may differ between
            reports; alignment is by column name, missing values filled with
            ``None``.
        column_order: Optional output column order. If ``None``, uses the first
            report's column order then appends new columns from later reports.

    Returns:
        A single ``SheetData`` with all rows stacked.
    """
    if column_order is not None:
        # Apply the desired column order as a final projection so the output
        # matches the user's requested schema exactly.
        stacked = union(reports)
        return project(stacked, columns=column_order)
    return union(reports)
