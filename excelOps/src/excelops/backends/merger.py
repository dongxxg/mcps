"""openpyxl-based xlsx merger — preserves visual formatting from file_a.

Merges two xlsx workbooks by Sheet name, using file_a as the format source
of truth. Column alignment is union-based (missing columns filled with None).
No deduplication is performed. Source files are never modified.

Design decisions: see .harness/spec/changes/excel-merge/design.md (D1–D5).
"""

from __future__ import annotations

from pathlib import Path
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from ..errors import MergeError
from .models import MergeResult, SheetData
from .reader import _normalize_header, read_sheet

__all__ = ["merge_workbook"]

# openpyxl raises these for a wrong-type or corrupted file — mirrors reader.py
_UNSUPPORTED = (InvalidFileException, BadZipFile, KeyError, ParseError, OSError)


def _require_xlsx(path: Path) -> None:
    """Validate that ``path`` exists and is a parseable xlsx.

    Raises MergeError (not ReadError) so callers don't need to know which
    engine is doing the validation.
    """
    if not path.exists():
        raise MergeError(f"source file not found: {path}")
    try:
        load_workbook(path, read_only=True).close()
    except _UNSUPPORTED as e:
        raise MergeError(f"not a valid xlsx: {path} ({type(e).__name__})") from e


def _column_index_map(columns: tuple[str, ...]) -> dict[str, int]:
    """Map column name -> positional index for alignment lookups."""
    return {name: i for i, name in enumerate(columns)}


def _align_columns(
    a_cols: tuple[str, ...], b_cols: tuple[str, ...]
) -> tuple[tuple[str, ...], list[int | None], list[int | None]]:
    """Union column alignment.

    Returns ``(merged_cols, a_mapping, b_mapping)`` where:
      - ``merged_cols`` is the union of a_cols + b_cols (a order first, then
        b-only columns appended).
      - ``a_mapping[j]`` is the index in a_cols that maps to merged_cols[j],
        or None when merged_cols[j] is b-only.
      - ``b_mapping[j]`` is the index in b_cols that maps to merged_cols[j],
        or None when merged_cols[j] is a-only.
    """
    merged = list(a_cols)
    a_mapping: list[int | None] = list(range(len(a_cols)))
    b_mapping: list[int | None] = [None] * len(a_cols)

    b_index = _column_index_map(b_cols)
    for j, name in enumerate(a_cols):
        if name in b_index:
            b_mapping[j] = b_index[name]

    for name in b_cols:
        if name not in a_cols:
            merged.append(name)
            a_mapping.append(None)
            b_mapping.append(b_index[name])

    return tuple(merged), a_mapping, b_mapping


def _remap_row(
    row: tuple, mapping: list[int | None], n: int
) -> tuple:
    """Remap a source row to merged column order using ``mapping``.

    ``mapping[j]`` is the source column index for merged position j, or None
    when the source lacks that column (filled with None).
    """
    result = []
    for j in range(n):
        src_idx = mapping[j]
        if src_idx is None:
            result.append(None)
        else:
            result.append(row[src_idx] if src_idx < len(row) else None)
    return tuple(result)


def _copy_cell_style(src, dst) -> None:
    """Copy font, fill, alignment, border from src cell to dst cell."""
    if src.has_style:
        dst.font = src.font.copy() if src.font else dst.font
        dst.fill = src.fill.copy() if src.fill else dst.fill
        dst.alignment = src.alignment.copy() if src.alignment else dst.alignment
        dst.border = src.border.copy() if src.border else dst.border
        dst.number_format = src.number_format


def _write_row_with_style(ws, row_idx: int, values: tuple, style_source_row) -> None:
    """Write ``values`` to ``row_idx``, copying style from ``style_source_row``."""
    for col_idx, val in enumerate(values, start=1):
        cell = ws.cell(row=row_idx, column=col_idx, value=val)
        if style_source_row is not None:
            src_cell = style_source_row[col_idx - 1]
            _copy_cell_style(src_cell, cell)


def merge_workbook(
    path_a: str | Path,
    path_b: str | Path,
    out_path: str | Path,
) -> MergeResult:
    """Merge two xlsx workbooks into a new file.

    file_a is the format source of truth — its column widths, cell styles,
    merged cells, and row heights are preserved. file_b contributes only
    data (read via streaming reader). Sheets are paired by name; sheets
    present in only one file are kept as-is.

    Args:
        path_a: First source workbook (format baseline).
        path_b: Second source workbook (data only).
        out_path: Destination path for the merged workbook.

    Returns:
        MergeResult with path, bytes_written, rows_written, sheets.

    Raises:
        MergeError: If either source is missing/invalid, or output dir
            does not exist.
    """
    path_a = Path(path_a)
    path_b = Path(path_b)
    out_path = Path(out_path)

    # --- validate inputs ---
    _require_xlsx(path_a)
    _require_xlsx(path_b)

    # Guard: out_path must not be the same as either source file.
    # Without this, load_workbook(path_a) + wb_a.save(path_a) would silently
    # overwrite the source — violating the "source files never modified" invariant.
    out_resolved = out_path.resolve()
    if out_resolved == path_a.resolve() or out_resolved == path_b.resolve():
        raise MergeError(
            f"out_path must not be the same as either source file: {out_path}"
        )

    parent = out_path.parent
    if not parent.exists():
        raise MergeError(f"output directory does not exist: {parent}")

    # --- load file_a with styles (full load, not streaming) ---
    wb_a = load_workbook(path_a)

    # --- read file_b sheets as SheetData (streaming, memory-friendly) ---
    b_sheet_names = set()
    b_data: dict[str, SheetData] = {}
    for sname in load_workbook(path_b, read_only=True).sheetnames:
        b_sheet_names.add(sname)
        b_data[sname] = read_sheet(path_b, sname)

    rows_written = 0

    # --- merge each sheet present in either workbook ---
    all_sheet_names = list(wb_a.sheetnames)
    for sname in b_sheet_names:
        if sname not in all_sheet_names:
            all_sheet_names.append(sname)

    for sname in all_sheet_names:
        in_a = sname in wb_a.sheetnames
        in_b = sname in b_sheet_names

        if in_a and in_b:
            ws_a = wb_a[sname]
            sd_b = b_data[sname]

            # Determine column headers from file_a (row 1).
            # Merged cells read as None — fill them from the merge range's
            # top-left value so column comparison is accurate.
            a_raw_headers = _read_header_row(ws_a)
            # Normalize a's headers the same way reader does
            a_cols = _normalize_header(a_raw_headers)
            b_cols = sd_b.columns

            if a_cols == b_cols:
                # Fast path: identical columns — direct append.
                # Merged cells and all formatting stay untouched.
                start_row = ws_a.max_row + 1
                # Use the last data row of a as style source (safer than row 2
                # when a has merged header + single data row)
                style_source = ws_a[ws_a.max_row] if ws_a.max_row >= 2 else None
                for offset, row in enumerate(sd_b.rows):
                    _write_row_with_style(
                        ws_a, start_row + offset, row, style_source
                    )
            else:
                # Remember row-1 merges before we unmerge (for potential
                # re-creation after header rewrite).
                header_merges = [
                    (mr.min_col, mr.max_col)
                    for mr in ws_a.merged_cells.ranges
                    if mr.min_row == 1 and mr.max_row == 1
                ]
                # Union path: remap both a and b rows
                merged_cols, a_mapping, b_mapping = _align_columns(a_cols, b_cols)

                # Unmerge all merged cells before rewriting headers
                # (merged cells are read-only and would crash writes).
                all_merges = list(ws_a.merged_cells.ranges)
                for merged_range in all_merges:
                    ws_a.unmerge_cells(str(merged_range))

                # Rewrite header
                for c, name in enumerate(merged_cols, start=1):
                    ws_a.cell(row=1, column=c, value=name)

                # Re-create row-1 merges if they still fit within new column count
                for min_col, max_col in header_merges:
                    if max_col <= len(merged_cols):
                        ws_a.merge_cells(
                            start_row=1, start_column=min_col,
                            end_row=1, end_column=max_col
                        )

                # Rewrite existing a rows with remapped columns
                a_row_count = ws_a.max_row  # includes header
                if a_row_count > 1:
                    # Read existing data rows, remap, write back
                    old_a_rows = []
                    for r in range(2, a_row_count + 1):
                        row = tuple(
                            ws_a.cell(row=r, column=c).value
                            for c in range(1, ws_a.max_column + 1)
                        )
                        old_a_rows.append(row)
                    # Clear old data rows
                    for r in range(2, a_row_count + 1):
                        for c in range(1, ws_a.max_column + 1):
                            ws_a.cell(row=r, column=c).value = None
                    # Write remapped rows
                    for offset, row in enumerate(old_a_rows):
                        remapped = _remap_row(row, a_mapping, len(merged_cols))
                        _write_row_with_style(
                            ws_a, 2 + offset, remapped,
                            None  # keep existing style from a's original row
                        )

                # Append b rows remapped to merged column order
                start_row = ws_a.max_row + 1
                for offset, row in enumerate(sd_b.rows):
                    remapped = _remap_row(row, b_mapping, len(merged_cols))
                    _write_row_with_style(
                        ws_a, start_row + offset, remapped,
                        ws_a[2] if ws_a.max_row >= 2 else None
                    )
                    rows_written += 1

        elif in_b and not in_a:
            # Sheet only in b — create new sheet in output, write b's data
            ws_new = wb_a.create_sheet(sname)
            # Write header
            for c, name in enumerate(b_data[sname].columns, start=1):
                ws_new.cell(row=1, column=c, value=name)
            # Write data rows
            for offset, row in enumerate(b_data[sname].rows):
                for c, val in enumerate(row, start=1):
                    ws_new.cell(row=2 + offset, column=c, value=val)
                rows_written += 1

        # in_a and not in_b: sheet already in wb_a, nothing to do

    # --- save ---
    wb_a.save(out_path)

    # Count total data rows across all sheets (excluding header rows)
    rows_written = sum(
        max(0, wb_a[s].max_row - 1) for s in all_sheet_names if s in wb_a.sheetnames
    )

    bytes_written = out_path.stat().st_size if out_path.exists() else 0
    sheets = tuple(all_sheet_names)

    return MergeResult(
        path=out_path,
        bytes_written=bytes_written,
        rows_written=rows_written,
        sheets=sheets,
    )


def _read_header_row(ws) -> tuple:
    """Read row 1 (header) of a worksheet, filling merged-cell gaps.

    openpyxl returns ``None`` for cells covered by a merge range (only the
    top-left cell holds the value). For column-alignment to work correctly we
    need the real value in every position, so we walk the merged-cell ranges
    and back-fill from each range's top-left cell.
    """
    if ws.max_column == 0:
        return ()
    raw = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]
    for merged_range in ws.merged_cells.ranges:
        # Only fix merges that touch row 1
        if merged_range.min_row == 1 and merged_range.max_row == 1:
            top_left_val = raw[merged_range.min_col - 1]
            for c in range(merged_range.min_col, merged_range.max_col + 1):
                if raw[c - 1] is None:
                    raw[c - 1] = top_left_val
    return tuple(raw)


