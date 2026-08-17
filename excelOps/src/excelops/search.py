"""Cross-file search — find rows by priority-ordered field-value conditions.

Given a directory of ``.xlsx`` files and a priority-ordered list of
``(field, value)`` conditions, ``search_files()`` scans every sheet of every
file, returns a :class:`~excelops.SheetData` of matching rows annotated with
provenance columns (``__file__``, ``__sheet__``, ``__match_field__``,
``__priority__``) and a union of all source column names.

Design points:
    - Exact match only (``==``), type-faithful (no implicit str coercion).
    - One value per field; priority fallback — first hit wins.
    - Scans only ``.xlsx``, non-recursive; every sheet in every file.
    - No-match returns an empty ``SheetData`` (not an error).
    - Pure Python, no ``[duckdb]`` dependency.

Internal matching logic (``_match_rows``) is a pure function for independent
testing.
"""

from __future__ import annotations

from collections import namedtuple
from pathlib import Path
from typing import Any

from .backends.models import SheetData
from .backends.reader import list_sheets, read_sheet
from .errors import SearchError

__all__ = ["search_files"]

# Provenance columns attached to every result row.
_PROVENANCE = ("__file__", "__sheet__", "__match_field__", "__priority__")

# Internal record produced by _match_rows.
MatchInfo = namedtuple(
    "MatchInfo",
    ["row", "columns", "file", "sheet", "match_field", "priority"],
)


# ─── Public API ──────────────────────────────────────────────────────────────

def search_files(
    directory: str | Path,
    conditions: list[tuple[str, Any]],
) -> SheetData:
    """Search ``.xlsx`` files in *directory* by priority-ordered conditions.

    Args:
        directory: Target directory (must exist and contain ``.xlsx`` files).
        conditions: Priority-ordered ``[(field, value), ...]`` pairs. The first
            condition that matches a row wins; subsequent conditions are skipped
            for that row.

    Returns:
        A new :class:`~excelops.SheetData` whose rows are annotated with
        ``__file__``, ``__sheet__``, ``__match_field__``, ``__priority__`` and
        whose data columns are the union of all source files' columns (missing
        cells filled with ``None``). Rows are sorted by ``__priority__``
        ascending, then ``__file__`` ascending.

    Raises:
        SearchError: If *directory* does not exist, contains no ``.xlsx``
            files, or *conditions* is invalid.
    """
    directory = _validate_directory(directory)
    _validate_conditions(conditions)

    files = _glob_xlsx(directory)
    if not files:
        raise SearchError(f"no .xlsx files found in {directory!r}")

    hits: list[MatchInfo] = []
    for path in files:
        for sheet_name, data in _scan_file(path):
            hits.extend(
                _scan_sheet(data, sheet_name, path, conditions)
            )

    if not hits:
        return _empty_result(conditions, files)

    column_order = _build_result_column_order(hits)
    rows = _assemble_rows(hits, column_order)
    rows.sort(key=lambda r: (r[_PROVENANCE.index("__priority__")], r[_PROVENANCE.index("__file__")]))
    return SheetData(columns=_full_columns(column_order), rows=tuple(rows))


# ─── Validation ──────────────────────────────────────────────────────────────

def _validate_directory(directory: Path) -> Path:
    path = Path(directory)
    if not path.exists():
        raise SearchError(f"directory does not exist: {path!r}")
    if not path.is_dir():
        raise SearchError(f"path is not a directory: {path!r}")
    return path


def _validate_conditions(conditions: list[tuple[str, Any]]) -> None:
    if not conditions:
        raise SearchError("conditions must not be empty")
    for i, (field, _value) in enumerate(conditions):
        if not isinstance(field, str) or not field:
            raise SearchError(f"invalid field name at index {i}: {field!r}")


# ─── File scanning ───────────────────────────────────────────────────────────

def _glob_xlsx(directory: Path) -> list[Path]:
    """Return all ``.xlsx`` files in *directory* (non-recursive), sorted."""
    return sorted(
        p for p in directory.iterdir()
        if p.is_file() and p.suffix.lower() == ".xlsx"
    )


def _scan_file(path: Path) -> list[tuple[str, SheetData]]:
    """Read every sheet of an xlsx file → list of (sheet_name, SheetData).

    Silently skips empty sheets (no data rows). Files that cannot be opened
    are also silently skipped — the directory is the user's contract,
    individual file corruption is not a SearchError.
    """
    try:
        sheet_names = list_sheets(path)
    except Exception:
        return []

    result: list[tuple[str, SheetData]] = []
    for name in sheet_names:
        try:
            data = read_sheet(path, name)
        except Exception:
            continue
        if data.columns:
            result.append((name, data))
    return result


# ─── Matching (pure function) ────────────────────────────────────────────────

def _match_rows(
    data: SheetData,
    conditions: list[tuple[str, Any]],
) -> list[tuple[tuple, int, str]]:
    """Find matching rows in a single :class:`~excelops.SheetData`.

    This is the core matching logic — a pure function with no I/O. For each
    row, it tries conditions in priority order; the first hit wins. Returns
    a list of ``(row, priority, match_field)`` tuples.

    Type-faithful comparison: uses Python native ``==`` (no type coercion).
    ``123 == "123"`` is False; ``123 == 123.0`` is True; ``None == None`` is True.
    """
    columns = list(data.columns)
    hits: list[tuple[tuple, int, str]] = []

    for row in data.rows:
        for priority, (field, value) in enumerate(conditions):
            if field not in columns:
                continue
            idx = columns.index(field)
            cell = row[idx] if idx < len(row) else None
            if _values_equal(cell, value):
                hits.append((row, priority, field))
                break
    return hits


def _values_equal(a: Any, b: Any) -> bool:
    """Type-faithful equality — Python native ``==``."""
    return a == b


def _scan_sheet(
    data: SheetData,
    sheet_name: str,
    path: Path,
    conditions: list[tuple[str, Any]],
) -> list[MatchInfo]:
    """Match rows in a single sheet, return provenance-annotated hits."""
    matches = _match_rows(data, conditions)
    return [
        MatchInfo(
            row=row,
            columns=data.columns,
            file=path.name,
            sheet=sheet_name,
            match_field=field,
            priority=priority,
        )
        for row, priority, field in matches
    ]


# ─── Result assembly ─────────────────────────────────────────────────────────

def _build_result_column_order(hits: list[MatchInfo]) -> tuple[str, ...]:
    """Build the data-column order: first-file column order + later-file appends."""
    order: list[str] = []
    seen: set[str] = set()
    for hit in hits:
        for col in hit.columns:
            if col not in seen:
                seen.add(col)
                order.append(col)
    return tuple(order)


def _full_columns(data_columns: tuple[str, ...]) -> tuple[str, ...]:
    """Prepend provenance columns to data columns."""
    return _PROVENANCE + data_columns


def _assemble_rows(
    hits: list[MatchInfo],
    column_order: tuple[str, ...],
) -> list[tuple]:
    """Convert hits to result rows with provenance prefix + column-union values."""
    col_index = {col: i for i, col in enumerate(column_order)}
    rows: list[tuple] = []
    for hit in hits:
        # Build data values aligned to column_order.
        values: list[Any] = [None] * len(column_order)
        for i, src_val in enumerate(hit.row):
            col_name = hit.columns[i] if i < len(hit.columns) else None
            if col_name is not None and col_name in col_index:
                values[col_index[col_name]] = src_val

        row = (
            hit.file,
            hit.sheet,
            hit.match_field,
            hit.priority,
            *values,
        )
        rows.append(row)
    return rows


def _empty_result(
    conditions: list[tuple[str, Any]],
    files: list[Path],
) -> SheetData:
    """Return an empty SheetData with provenance + best-effort column order."""
    columns: list[str] = []
    seen: set[str] = set()
    for path in files:
        try:
            for _, data in _scan_file(path):
                for col in data.columns:
                    if col not in seen:
                        seen.add(col)
                        columns.append(col)
        except Exception:
            continue
    return SheetData(columns=_full_columns(tuple(columns)), rows=())