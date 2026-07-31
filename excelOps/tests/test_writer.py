"""Tests for the xlsxwriter-based writer with Copy-on-Write (backends/writer.py).

Covers the excel-write spec: multi-sheet write, the 5-step CoW contract
(same-dir temp -> flush+fsync -> atomic replace -> clean on failure), target
locked -> FileLocked, structured WriteResult without input mutation, write ->
read round-trip, and typed write errors.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from excelops.backends import reader, writer
from excelops.backends.models import SheetData
from excelops.errors import FileLocked, WriteError


def _leftover_tmps(d: Path) -> list[Path]:
    return [p for p in d.iterdir() if p.name.endswith(".tmp")]


# ---------------------------------------------------------------------------
# write_workbook (5.1)
# ---------------------------------------------------------------------------


def test_multi_sheet_write_roundtrips(tmp_path: Path):
    target = tmp_path / "out.xlsx"
    sdA = SheetData(columns=("region", "amount"), rows=(("east", 100), ("west", 200)))
    sdB = SheetData(columns=("note",), rows=(("x",),))

    writer.write_workbook(target, {"汇总": sdA, "明细": sdB})

    assert reader.list_sheets(target) == ["汇总", "明细"]
    assert reader.read_sheet(target, "汇总").rows == sdA.rows
    assert reader.read_sheet(target, "明细").rows == sdB.rows


def test_empty_rows_writes_header_only(tmp_path: Path):
    target = tmp_path / "out.xlsx"
    sd = SheetData(columns=("a", "b"), rows=())

    writer.write_workbook(target, {"s": sd})

    back = reader.read_sheet(target, "s")
    assert back.columns == ("a", "b")
    assert back.rows == ()


def test_empty_columns_and_rows_raises(tmp_path: Path):
    target = tmp_path / "out.xlsx"
    sd = SheetData(columns=(), rows=())
    with pytest.raises(WriteError):
        writer.write_workbook(target, {"s": sd})


def test_missing_parent_dir_raises(tmp_path: Path):
    target = tmp_path / "nope" / "out.xlsx"
    sd = SheetData(columns=("a",), rows=((1,),))
    with pytest.raises(WriteError):
        writer.write_workbook(target, {"s": sd})


# ---------------------------------------------------------------------------
# CoW contract (5.2)
# ---------------------------------------------------------------------------


def test_successful_write_no_temp_leftover(tmp_path: Path):
    target = tmp_path / "out.xlsx"
    sd = SheetData(columns=("a",), rows=((1,),))

    writer.write_workbook(target, {"s": sd})

    assert target.exists()
    assert _leftover_tmps(tmp_path) == []


def test_failed_write_preserves_existing_and_cleans_temp(tmp_path: Path, monkeypatch):
    target = tmp_path / "out.xlsx"
    sd = SheetData(columns=("a",), rows=((1,),))

    # first write succeeds; capture the on-disk bytes
    writer.write_workbook(target, {"s": sd})
    original_bytes = target.read_bytes()

    # inject failure at the atomic-replace step
    import excelops.backends.writer as w

    def boom(src, dst):
        raise OSError("injected failure")

    monkeypatch.setattr(w.os, "replace", boom)

    with pytest.raises(WriteError):
        writer.write_workbook(target, {"s": sd})

    # existing target untouched
    assert target.read_bytes() == original_bytes
    # no temp leftover
    assert _leftover_tmps(tmp_path) == []


# ---------------------------------------------------------------------------
# target locked -> FileLocked (5.3)
# ---------------------------------------------------------------------------


def test_target_locked_raises_file_locked(tmp_path: Path, monkeypatch):
    target = tmp_path / "out.xlsx"
    sd = SheetData(columns=("a",), rows=((1,),))

    import excelops.backends.writer as w

    monkeypatch.setattr(w, "_REPLACE_BACKOFF", 0.0)

    def locked(src, dst):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(w.os, "replace", locked)

    with pytest.raises(FileLocked):
        writer.write_workbook(target, {"s": sd})

    assert _leftover_tmps(tmp_path) == []


# ---------------------------------------------------------------------------
# structured result + no mutation (5.4 / D9)
# ---------------------------------------------------------------------------


def test_returns_result_and_does_not_mutate_input(tmp_path: Path):
    target = tmp_path / "out.xlsx"
    sd = SheetData(columns=("a",), rows=((1,), (2,)))
    before = (sd.columns, sd.rows)

    result = writer.write_workbook(target, {"s": sd}, source_ref="src")

    assert result.path == target
    assert result.bytes_written > 0
    assert result.rows_written == 2
    assert result.source_ref == "src"
    # input not mutated
    assert (sd.columns, sd.rows) == before


def test_write_then_read_roundtrip(tmp_path: Path):
    target = tmp_path / "out.xlsx"
    sd = SheetData(columns=("region", "amount"), rows=(("east", 100),))

    writer.write_workbook(target, {"orders": sd})

    back = reader.read_sheet(target, "orders")
    assert back.columns == sd.columns
    assert back.rows == sd.rows
