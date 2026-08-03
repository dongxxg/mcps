"""Shared, pandas-free data model crossing reader → analyzer → writer.

``SheetData(columns, rows)`` is the single spine type. It is a frozen dataclass
holding tuples, which makes it immutable, hashable, JSON-serializable, and safe
to hand between engines without defensive copies. Downstream engines may assume
``columns`` is always a tuple of non-empty unique strings and every row tuple
has length ``len(columns)`` (the reader enforces this — see design decision D10).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SheetData:
    """One worksheet as columns + rows (no pandas).

    Attributes:
        columns: Header names — always non-empty, unique, normalized by the
            reader before reaching downstream engines.
        rows: Data rows; each tuple has length ``len(columns)``.
    """

    columns: tuple[str, ...]
    rows: tuple[tuple, ...]


@dataclass(frozen=True)
class SheetMeta:
    """Used-region dimensions of a worksheet."""

    max_row: int
    max_col: int


@dataclass(frozen=True)
class MergeResult:
    """Outcome of a merge operation (returned by ``merge_workbook``).

    Attributes:
        path: Final output path of the merged workbook.
        bytes_written: Size of the written file in bytes.
        rows_written: Total data rows written across all sheets.
        sheets: Names of all sheets in the merged workbook.
    """

    path: Path
    bytes_written: int
    rows_written: int
    sheets: tuple[str, ...]


@dataclass(frozen=True)
class WriteResult:
    """Outcome of a write operation (returned by ``write_workbook``).

    Attributes:
        path: Final (replaced) target path of the written workbook.
        bytes_written: Size of the written file in bytes.
        rows_written: Total data rows written across all sheets.
        source_ref: Optional provenance label (e.g. source file/sheet name) for
            Phase 2 audit; may be ``None``.
    """

    path: Path
    bytes_written: int
    rows_written: int
    source_ref: str | None = None
