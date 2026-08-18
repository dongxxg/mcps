"""Tests for the export helper."""

from __future__ import annotations

from pathlib import Path

import pytest

from excelops.backends.models import SheetData
from excelops_gui.exporter import export_to_xlsx


def test_export_creates_valid_xlsx(tmp_path: Path) -> None:
    sd = SheetData(columns=("a", "b"), rows=(((1, "x"), (2, "y"))))
    out = tmp_path / "out.xlsx"
    result = export_to_xlsx(sd, out)
    assert out.exists()
    assert result.rows_written == 2
    assert result.path == out


def test_export_empty_rows_writes_header_only(tmp_path: Path) -> None:
    sd = SheetData(columns=("a",), rows=())
    out = tmp_path / "empty.xlsx"
    result = export_to_xlsx(sd, out)
    assert out.exists()
    assert result.rows_written == 0


def test_export_missing_parent_raises(tmp_path: Path) -> None:
    sd = SheetData(columns=("a",), rows=())
    bad = tmp_path / "nested" / "nope.xlsx"
    with pytest.raises(ValueError, match="parent directory does not exist"):
        export_to_xlsx(sd, bad)
