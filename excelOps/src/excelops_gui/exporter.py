"""Export support — write a ``SheetData`` to a new xlsx workbook.

The worker :class:`excelops_gui.workers.ExportWorker` calls
:meth:`export_to_xlsx` from a background thread so the UI stays responsive
on large datasets.
"""

from __future__ import annotations

from pathlib import Path

from excelops.backends.models import SheetData, WriteResult
from excelops.backends.writer import write_workbook


def export_to_xlsx(
    sheet_data: SheetData,
    path: str | Path,
    sheet_name: str = "结果",
) -> WriteResult:
    """Write *sheet_data* as a single-sheet workbook at *path*."""
    path = Path(path)
    parent = path.parent
    if not parent.exists():
        raise ValueError(f"parent directory does not exist: {parent}")
    return write_workbook(path, {sheet_name: sheet_data}, source_ref=str(path))
