"""Tests for the openpyxl-based reader (backends/reader.py).

Covers the excel-read spec scenarios: sheet enumeration, header / no-header
reads, ragged-row padding, header normalization, mixed-type fidelity, sheet
metadata, and typed errors (ReadError / UnsupportedFormat).
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from excelops.backends import reader
from excelops.backends.models import SheetData
from excelops.errors import ReadError, UnsupportedFormat

# ---------------------------------------------------------------------------
# list_sheets (3.1)
# ---------------------------------------------------------------------------


def test_list_sheets_returns_ordered_names(sample_workbook: Path):
    names = reader.list_sheets(sample_workbook)
    assert names == ["orders", "Summary", "Data"]


def test_list_sheets_missing_file_raises_read_error(tmp_path: Path):
    with pytest.raises(ReadError):
        reader.list_sheets(tmp_path / "does_not_exist.xlsx")


def test_list_sheets_corrupt_raises_unsupported_format(corrupt_xlsx: Path):
    with pytest.raises(UnsupportedFormat):
        reader.list_sheets(corrupt_xlsx)


# ---------------------------------------------------------------------------
# read_sheet (3.2)
# ---------------------------------------------------------------------------


def test_read_sheet_with_header(sample_workbook: Path):
    sd = reader.read_sheet(sample_workbook, "orders")
    assert isinstance(sd, SheetData)
    assert sd.columns == ("region", "amount")
    assert sd.rows == (("east", 100), ("west", 200), ("east", 50))


def test_read_sheet_no_header_positional(sample_workbook: Path):
    sd = reader.read_sheet(sample_workbook, "orders", header=False)
    assert sd.columns == ("col_0", "col_1")
    # rows include the original header row
    assert sd.rows[0] == ("region", "amount")
    assert len(sd.rows) == 4


def test_read_sheet_ragged_row_padded(ragged_header_workbook: Path):
    sd = reader.read_sheet(ragged_header_workbook, "sh")
    n = len(sd.columns)
    for row in sd.rows:
        assert len(row) == n  # every row aligned to column count
    # the ragged last row's missing tail cell is None
    assert sd.rows[-1] == ("c", "d", None)


def test_read_sheet_duplicate_header_normalized(ragged_header_workbook: Path):
    sd = reader.read_sheet(ragged_header_workbook, "sh")
    # three distinct, non-empty identifiers; duplicate "name" made unique
    assert len(set(sd.columns)) == len(sd.columns)
    assert all(c for c in sd.columns)
    assert sd.columns[0] == "name"
    assert sd.columns[2] == "amount"
    # the duplicate got a suffix
    assert sd.columns[1].startswith("name")


def test_read_sheet_mixed_types_preserved(mixed_types_workbook: Path):
    sd = reader.read_sheet(mixed_types_workbook, "mt")
    r0 = sd.rows[0]
    # date stays a date object (not ISO string / Excel serial)
    assert isinstance(r0[0], (date, datetime))
    assert not isinstance(r0[0], str)
    # nullable stays None
    assert r0[1] is None
    # float stays float
    assert isinstance(r0[2], float)
    # text stays str
    assert isinstance(r0[3], str)


def test_read_sheet_missing_sheet_lists_available(sample_workbook: Path):
    with pytest.raises(ReadError) as ei:
        reader.read_sheet(sample_workbook, "nope")
    msg = str(ei.value)
    assert "orders" in msg and "Summary" in msg and "Data" in msg


def test_read_sheet_missing_file_raises_read_error(tmp_path: Path):
    with pytest.raises(ReadError):
        reader.read_sheet(tmp_path / "nope.xlsx", "Sheet1")


def test_read_sheet_corrupt_raises_unsupported_format(corrupt_xlsx: Path):
    with pytest.raises(UnsupportedFormat):
        reader.read_sheet(corrupt_xlsx, "Sheet1")


# ---------------------------------------------------------------------------
# sheet_meta (3.3)
# ---------------------------------------------------------------------------


def test_sheet_meta_dimensions(sample_workbook: Path):
    meta = reader.sheet_meta(sample_workbook, "orders")
    # header + 3 data rows = 4 rows; 2 columns
    assert meta.max_row == 4
    assert meta.max_col == 2


def test_sheet_meta_missing_sheet_raises_read_error(sample_workbook: Path):
    with pytest.raises(ReadError):
        reader.sheet_meta(sample_workbook, "nope")
