"""``project_columns`` recipe — column projection alias."""

from __future__ import annotations

from ..backends.models import SheetData
from .project import project

__all__ = ["project_columns"]


def project_columns(
    sd: SheetData,
    columns: list[str],
    rename: dict[str, str] | None = None,
) -> SheetData:
    """Select, reorder, and optionally rename columns (alias for :func:`project`).

    This is the semantically-named entry point for the "从系统中导出一张表，
   只选取需要的那几列" workflow.
    """
    return project(sd, columns, rename)
