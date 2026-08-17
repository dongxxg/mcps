"""Cross-file search — find rows by priority-ordered field-value conditions.

Given a directory of ``.xlsx`` files and a priority-ordered list of conditions,
``search_files()`` scans every sheet of every file, returns a
:class:`~excelops.SheetData` of matching rows annotated with provenance columns
(``__file__``, ``__sheet__``, ``__match_field__``, ``__priority__``) and a union
of all source column names.

Design points:
    - Two match modes: ``"exact"`` (``==``, type-faithful) and ``"contains"``
      (case-insensitive substring, both sides must be strings).
    - Per-condition mode: pass ``(field, value, mode)`` triples; the ``mode``
      parameter sets the global default for plain ``(field, value)`` pairs.
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
from typing import Any, Literal, overload

from .backends.models import SheetData
from .backends.reader import list_sheets, read_sheet
from .errors import SearchError

__all__ = ["search_files"]

MatchMode = Literal["exact", "contains"]

# Provenance columns attached to every result row.
_PROVENANCE = ("__file__", "__sheet__", "__match_field__", "__priority__")
_PRIORITY_IDX = _PROVENANCE.index("__priority__")
_FILE_IDX = _PROVENANCE.index("__file__")

# Internal record produced by _scan_sheet.
MatchInfo = namedtuple(
    "MatchInfo",
    ["row", "columns", "file", "sheet", "match_field", "priority"],
)

# Internal record produced by _scan_file.
FileResult = namedtuple(
    "FileResult",
    ["file", "columns_order", "hits", "no_hit_columns"],
)

# Normalized condition: (field, value, mode).
_NormalizedCondition = tuple[str, Any, str]


# ─── Public API ──────────────────────────────────────────────────────────────

@overload
def search_files(
    directory: str | Path,
    conditions: list[tuple[str, Any]],
    mode: MatchMode = "exact",
) -> SheetData:
    ...


@overload
def search_files(
    directory: str | Path,
    conditions: list[tuple[str, Any] | tuple[str, Any, MatchMode]],
    mode: MatchMode = "exact",
) -> SheetData:
    ...


def search_files(
    directory: str | Path,
    conditions: list[tuple[str, Any]] | list[tuple[str, Any, MatchMode]],
    mode: MatchMode = "exact",
) -> SheetData:
    """Search ``.xlsx`` files in *directory* by priority-ordered conditions.

    Args:
        directory: Target directory (must exist and contain ``.xlsx`` files).
        conditions: Priority-ordered condition list. Each condition is either
            ``(field, value)`` (uses *mode* as its match mode) or
            ``(field, value, mode)`` (per-condition mode override). The first
            condition that matches a row wins; subsequent conditions are skipped
            for that row.
        mode: Default match mode for conditions without an explicit mode.
            ``"exact"`` uses ``==`` (type-faithful); ``"contains"`` does
            case-insensitive substring matching (both sides must be strings).

    Returns:
        A new :class:`~excelops.SheetData` whose rows are annotated with
        ``__file__``, ``__sheet__``, ``__match_field__``, ``__priority__`` and
        whose data columns are the union of all source files' columns (missing
        cells filled with ``None``). Rows are sorted by ``__priority__``
        ascending, then ``__file__`` ascending.

    Raises:
        SearchError: If *directory* does not exist, contains no ``.xlsx``
            files, or *conditions* / *mode* is invalid.
    """
    directory = _validate_directory(directory)
    _validate_mode(mode)
    normalized = _normalize_conditions(conditions, mode)
    _validate_conditions(normalized)

    files = _glob_xlsx(directory)
    if not files:
        raise SearchError(f"no .xlsx files found in {directory!r}")

    results = [_scan_file(path, normalized) for path in files]
    results.sort(key=lambda r: r.file)

    all_hits = [h for r in results for h in r.hits]
    column_order = _build_full_column_order(results)

    if not all_hits:
        return SheetData(columns=_full_columns(column_order), rows=())

    rows = _assemble_rows(all_hits, column_order)
    rows.sort(key=lambda r: (r[_PRIORITY_IDX], r[_FILE_IDX]))
    return SheetData(columns=_full_columns(column_order), rows=tuple(rows))


# ─── Validation & normalization ──────────────────────────────────────────────

def _validate_directory(directory: Path) -> Path:
    path = Path(directory)
    if not path.exists():
        raise SearchError(f"directory does not exist: {path!r}")
    if not path.is_dir():
        raise SearchError(f"path is not a directory: {path!r}")
    return path


def _validate_mode(mode: str) -> None:
    if mode not in ("exact", "contains"):
        raise SearchError(f"invalid mode {mode!r}; must be 'exact' or 'contains'")


def _normalize_conditions(
    conditions: list[tuple[str, Any]] | list[tuple[str, Any, MatchMode]],
    default_mode: str,
) -> list[_NormalizedCondition]:
    """Normalize to list of (field, value, mode) triples."""
    normalized: list[_NormalizedCondition] = []
    for i, cond in enumerate(conditions):
        n = len(cond)
        if n == 2:
            field, value = cond
            normalized.append((field, value, default_mode))
        elif n == 3:
            field, value, cond_mode = cond
            _validate_mode(cond_mode)
            normalized.append((field, value, cond_mode))
        else:
            raise SearchError(
                f"condition at index {i} must have 2 or 3 elements, "
                f"got {n}"
            )
    return normalized


def _validate_conditions(conditions: list[_NormalizedCondition]) -> None:
    if not conditions:
        raise SearchError("conditions must not be empty")
    for i, (field, _value, _mode) in enumerate(conditions):
        if not isinstance(field, str) or not field.strip():
            raise SearchError(f"invalid field name at index {i}: {field!r}")


# ─── File scanning ───────────────────────────────────────────────────────────

def _glob_xlsx(directory: Path) -> list[Path]:
    """Return all ``.xlsx`` files in *directory* (non-recursive), sorted."""
    return sorted(
        p for p in directory.iterdir()
        if p.is_file() and p.suffix.lower() == ".xlsx"
    )


def _scan_file(
    path: Path,
    conditions: list[_NormalizedCondition],
) -> FileResult:
    """Read an xlsx file, return hits + column order for this file."""
    try:
        sheet_names = list_sheets(path)
    except Exception:
        return FileResult(path.name, (), [], ())

    file_hits: list[MatchInfo] = []
    col_order: list[str] = []
    col_seen: set[str] = set()

    for name in sheet_names:
        try:
            data = read_sheet(path, name)
        except Exception:
            continue
        for col in data.columns:
            if col not in col_seen:
                col_seen.add(col)
                col_order.append(col)
        file_hits.extend(
            _scan_sheet(data, name, path, conditions)
        )

    return FileResult(path.name, tuple(col_order), file_hits, ())


# ─── Column order ────────────────────────────────────────────────────────────

def _build_full_column_order(results: list[FileResult]) -> tuple[str, ...]:
    """Build the data-column order across all files (hit + no-hit columns).

    Files are already sorted by filename, so the first occurrence of each
    column wins for ordering.
    """
    order: list[str] = []
    seen: set[str] = set()
    for result in results:
        for col in result.columns_order:
            if col not in seen:
                seen.add(col)
                order.append(col)
    return tuple(order)


def _full_columns(data_columns: tuple[str, ...]) -> tuple[str, ...]:
    """Prepend provenance columns to data columns."""
    return _PROVENANCE + data_columns


# ─── Matching (pure function) ────────────────────────────────────────────────

def _match_rows(
    data: SheetData,
    conditions: list[_NormalizedCondition],
) -> list[tuple[tuple, int, str]]:
    """Find matching rows in a single :class:`~excelops.SheetData`.

    This is the core matching logic — a pure function with no I/O. For each
    row, it tries conditions in priority order; the first hit wins. Returns
    a list of ``(row, priority, match_field)`` tuples.

    Match modes:
        - ``exact``: type-faithful ``==`` — ``123 == "123"`` is False,
          ``123 == 123.0`` is True, ``None == None`` is True.
        - ``contains``: case-insensitive substring — both cell and value must
          be strings; ``value.lower() in cell.lower()``. Non-string cells
          never match.
    """
    columns = list(data.columns)
    col_index = {c: i for i, c in enumerate(columns)}
    hits: list[tuple[tuple, int, str]] = []

    for row in data.rows:
        for priority, (field, value, mode) in enumerate(conditions):
            idx = col_index.get(field)
            if idx is None:
                continue
            cell = row[idx] if idx < len(row) else None
            if _match(cell, value, mode):
                hits.append((row, priority, field))
                break
    return hits


def _match(cell: Any, value: Any, mode: str) -> bool:
    """Apply the given match mode to compare *cell* against *value*."""
    if mode == "exact":
        return _values_equal(cell, value)
    return _values_contains(cell, value)


def _values_equal(a: Any, b: Any) -> bool:
    """Type-faithful equality — Python native ``==``."""
    return a == b


def _values_contains(cell: Any, value: Any) -> bool:
    """Case-insensitive substring: ``value.lower() in cell.lower()``.

    Both *cell* and *value* must be strings. Non-string cells never match
    (type-faithful: no implicit ``str()`` coercion). Comparison is
    case-insensitive for usability — ``"abc"`` matches ``"ABC 123"``.
    """
    if not isinstance(cell, str) or not isinstance(value, str):
        return False
    return value.lower() in cell.lower()


def _scan_sheet(
    data: SheetData,
    sheet_name: str,
    path: Path,
    conditions: list[_NormalizedCondition],
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

def _assemble_rows(
    hits: list[MatchInfo],
    column_order: tuple[str, ...],
) -> list[tuple]:
    """Convert hits to result rows with provenance prefix + column-union values."""
    col_index = {col: i for i, col in enumerate(column_order)}
    rows: list[tuple] = []
    for hit in hits:
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