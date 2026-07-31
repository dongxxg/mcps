"""Acceptance tests — the Phase 1 hard requirements (proposal §契约硬指标).

End-to-end, cross-engine verifications:
  6.1 closed loop: read -> analyze -> write -> re-read
  6.2 type fidelity across read -> write -> read
  6.3 large-file streaming smoke (bounded memory)
  6.4 typed error paths across all engines
  6.5 CoW observability (failed write preserves target + no temp leftover)
"""

from __future__ import annotations

import sys
import tracemalloc
from datetime import date, datetime
from pathlib import Path

import pytest
from openpyxl import Workbook

from excelops.backends import reader, writer
from excelops.backends.analyzer import Analyzer
from excelops.backends.models import SheetData
from excelops.errors import (
    AnalyzeError,
    FileLocked,
    MissingDependency,
    ReadError,
    UnsupportedFormat,
    WriteError,
)

# ---------------------------------------------------------------------------
# 6.1 closed loop
# ---------------------------------------------------------------------------


def test_closed_loop_read_analyze_write(sample_workbook: Path):
    orders = reader.read_sheet(sample_workbook, "orders")

    with Analyzer() as az:
        az.register("orders", orders)
        result = az.query(
            "SELECT region, sum(amount) AS total "
            "FROM orders GROUP BY region ORDER BY region"
        )

    out = sample_workbook.parent / "result.xlsx"
    writer.write_workbook(out, {"agg": result})

    back = reader.read_sheet(out, "agg")
    assert back.columns == ("region", "total")
    assert back.rows == (("east", 150), ("west", 200))


# ---------------------------------------------------------------------------
# 6.2 type fidelity across read -> write -> read
# ---------------------------------------------------------------------------


def test_type_fidelity_roundtrip(mixed_types_workbook: Path, tmp_path: Path):
    sd = reader.read_sheet(mixed_types_workbook, "mt")

    out = tmp_path / "rt.xlsx"
    writer.write_workbook(out, {"mt": sd})

    back = reader.read_sheet(out, "mt")
    assert back.columns == sd.columns

    for row in back.rows:
        # date column stays a date object, not ISO string / Excel serial
        assert isinstance(row[0], (date, datetime))
        assert not isinstance(row[0], str)
        # float column stays float
        assert isinstance(row[2], float)
        # text column stays str
        assert isinstance(row[3], str)
    # nullable column: None preserved exactly
    assert back.rows[0][1] is None
    assert back.rows[1][1] == 5


# ---------------------------------------------------------------------------
# 6.3 large-file streaming smoke (bounded memory)
# ---------------------------------------------------------------------------


def test_large_file_streaming(tmp_path: Path):
    n = 100_000
    big = tmp_path / "big.xlsx"
    wb = Workbook(write_only=True)
    ws = wb.create_sheet("data")
    ws.append(["id", "region", "amount"])
    for i in range(n):
        ws.append([i, "east" if i % 2 else "west", i * 1.5])
    ws2 = wb.create_sheet("meta")
    ws2.append(["k", "v"])
    ws2.append(["rows", n])
    wb.save(big)

    tracemalloc.start()
    try:
        sd = reader.read_sheet(big, "data")
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert len(sd.rows) == n
    assert sd.columns == ("id", "region", "amount")
    assert sd.rows[0][1] == "west"          # i=0 -> west
    assert sd.rows[-1][0] == n - 1
    # peak memory stays well below an OOM threshold for 100k rows
    assert peak < 512 * 1024 * 1024

    meta = reader.read_sheet(big, "meta")
    assert meta.rows[0] == ("rows", n)


# ---------------------------------------------------------------------------
# 6.4 typed error paths across all engines
# ---------------------------------------------------------------------------


def test_error_paths(tmp_path: Path, sample_workbook: Path, corrupt_xlsx: Path, monkeypatch):
    sd = SheetData(columns=("a",), rows=((1,),))

    # reader errors
    with pytest.raises(ReadError):
        reader.read_sheet(tmp_path / "missing.xlsx", "s")
    with pytest.raises(UnsupportedFormat):
        reader.read_sheet(corrupt_xlsx, "s")
    with pytest.raises(ReadError):
        reader.read_sheet(sample_workbook, "nope")

    # writer errors
    with pytest.raises(WriteError):
        writer.write_workbook(tmp_path / "nodir" / "o.xlsx", {"s": sd})

    import excelops.backends.writer as w

    def _locked(src, dst):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(w, "_REPLACE_BACKOFF", 0.0)
    monkeypatch.setattr(w.os, "replace", _locked)
    with pytest.raises(FileLocked):
        writer.write_workbook(tmp_path / "o.xlsx", {"s": sd})
    assert [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")] == []

    # analyze errors
    with Analyzer() as az:
        az.register("t", sd)
        with pytest.raises(AnalyzeError):
            az.query("SELECT FROMM t")

    monkeypatch.setitem(sys.modules, "duckdb", None)
    with pytest.raises(MissingDependency), Analyzer():
        pass


# ---------------------------------------------------------------------------
# 6.5 CoW observability
# ---------------------------------------------------------------------------


def test_cow_failure_preserves_target_and_cleans_temp(tmp_path: Path, monkeypatch):
    target = tmp_path / "out.xlsx"
    sd = SheetData(columns=("a",), rows=((1,),))

    writer.write_workbook(target, {"s": sd})
    original = target.read_bytes()

    import excelops.backends.writer as w

    def boom(src, dst):
        raise OSError("injected")

    monkeypatch.setattr(w.os, "replace", boom)
    with pytest.raises(WriteError):
        writer.write_workbook(target, {"s": sd})

    assert target.read_bytes() == original
    assert [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")] == []


def test_cow_success_full_result_no_leftover(tmp_path: Path):
    target = tmp_path / "out.xlsx"
    sd = SheetData(columns=("a", "b"), rows=((1, 2), (3, 4)))

    result = writer.write_workbook(target, {"s": sd}, source_ref="src")

    assert target.exists()
    assert result.path == target
    assert result.bytes_written > 0
    assert result.rows_written == 2
    assert result.source_ref == "src"
    assert [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")] == []
