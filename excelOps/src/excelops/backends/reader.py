"""openpyxl-based xlsx reader — the sole xlsx entry point (design D4).

Produces ``SheetData`` with schema discipline baked in (D10): ragged rows are
padded to ``len(columns)``, headers are normalized to unique non-empty names,
and native cell types (dates, numbers, bools) are preserved with no implicit
stringification. Reads stream via ``read_only=True`` so peak memory stays
decoupled from workbook physical size.
"""

from __future__ import annotations

from pathlib import Path
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from ..errors import ReadError, UnsupportedFormat
from .models import SheetData, SheetMeta

__all__ = ["list_sheets", "read_sheet", "sheet_meta"]

# openpyxl / zipfile / XML parser raise any of these for a wrong-type or
# corrupted file.
_UNSUPPORTED = (InvalidFileException, BadZipFile, KeyError, ParseError)


def _open(path: Path, data_only: bool):
    try:
        return load_workbook(path, read_only=True, data_only=data_only)
    except FileNotFoundError as e:
        raise ReadError(f"file not found: {path}") from e
    except _UNSUPPORTED as e:
        raise UnsupportedFormat(f"not a valid xlsx: {path} ({type(e).__name__})") from e


def _require_sheet(wb, sheet: str):
    if sheet not in wb.sheetnames:
        raise ReadError(
            f"sheet {sheet!r} not found; available sheets: {list(wb.sheetnames)}"
        )
    return wb[sheet]


def _normalize_header(raw: tuple) -> tuple[str, ...]:
    """Turn a raw first row into legal, unique, non-empty column names.

    None / blank -> ``col_{i}``; exact duplicates get a ``_1``, ``_2``... suffix.
    """
    cleaned: list[str] = []
    for i, v in enumerate(raw):
        if v is None or (isinstance(v, str) and v.strip() == ""):
            cleaned.append(f"col_{i}")
        else:
            cleaned.append(str(v))
    seen: set[str] = set()
    result: list[str] = []
    for name in cleaned:
        candidate = name
        k = 1
        while candidate in seen:
            candidate = f"{name}_{k}"
            k += 1
        seen.add(candidate)
        result.append(candidate)
    return tuple(result)


def _fit(row: tuple, n: int) -> tuple:
    """Pad a short row with None / truncate a long row to exactly ``n`` cells."""
    if len(row) >= n:
        return tuple(row[:n])
    return tuple(row) + (None,) * (n - len(row))


def list_sheets(path: str | Path) -> list[str]:
    """Return the workbook's sheet names in workbook order."""
    path = Path(path)
    wb = _open(path, data_only=False)
    try:
        return list(wb.sheetnames)
    finally:
        wb.close()


def read_sheet(
    path: str | Path,
    sheet: str,
    header: bool = True,
    data_only: bool = True,
) -> SheetData:
    """Read one sheet into a ``SheetData``.

    ``header=True`` (default) treats the first row as column names; ``header=False``
    reads positionally with synthetic ``col_0, col_1, ...`` names and keeps every
    row (including the original first row).
    """
    path = Path(path)
    wb = _open(path, data_only=data_only)
    try:
        ws = _require_sheet(wb, sheet)
        it = ws.iter_rows(values_only=True)
        try:
            first = next(it)
        except StopIteration:
            return SheetData(columns=(), rows=())

        if header:
            columns = _normalize_header(first)
        else:
            columns = _normalize_header(tuple(f"col_{i}" for i in range(len(first))))
        n = len(columns)

        rest = tuple(_fit(r, n) for r in it)
        rows = rest if header else (_fit(first, n),) + rest
        return SheetData(columns=columns, rows=rows)
    finally:
        wb.close()


def sheet_meta(path: str | Path, sheet: str) -> SheetMeta:
    """Return used-region dimensions (``max_row``, ``max_col``) of a sheet."""
    path = Path(path)
    wb = _open(path, data_only=False)
    try:
        ws = _require_sheet(wb, sheet)
        return SheetMeta(max_row=ws.max_row, max_col=ws.max_column)
    finally:
        wb.close()
