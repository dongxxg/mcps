"""Edge-case coverage that complements the per-engine test files.

Addresses gaps surfaced in the post-implementation review:
  - reader: None / blank header normalization, fully empty sheet
  - analyzer: empty-rows registration, ``::`` cast operator untouched
  - writer: empty sheets dict, happy overwrite, retry-then-recover, ragged rows
  - package: top-level public API exports
"""

from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook

import excelops
from excelops.backends import reader, writer
from excelops.backends.analyzer import Analyzer
from excelops.backends.models import SheetData
from excelops.errors import UnsupportedFormat, WriteError

# ---------------------------------------------------------------------------
# local fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def none_header_workbook(tmp_path: Path) -> Path:
    p = tmp_path / "none_hdr.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "sh"
    ws.append([None, "", "amount"])  # None + blank + valid
    ws.append(["a", "b", 1])
    wb.save(p)
    return p


@pytest.fixture
def empty_sheet_workbook(tmp_path: Path) -> Path:
    p = tmp_path / "empty.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "empty"
    # no rows at all
    wb.save(p)
    return p


# ---------------------------------------------------------------------------
# reader edge cases
# ---------------------------------------------------------------------------


def test_none_and_blank_header_normalized(none_header_workbook: Path):
    sd = reader.read_sheet(none_header_workbook, "sh")
    # None / blank become col_0 / col_1; valid name kept; all unique & non-empty
    assert sd.columns[0] == "col_0"
    assert sd.columns[1] == "col_1"
    assert sd.columns[2] == "amount"
    assert len(set(sd.columns)) == len(sd.columns)
    assert all(c for c in sd.columns)


def test_read_fully_empty_sheet(empty_sheet_workbook: Path):
    sd = reader.read_sheet(empty_sheet_workbook, "empty")
    assert sd.columns == ()
    assert sd.rows == ()


def test_sheet_meta_corrupt_raises(corrupt_xlsx: Path):
    with pytest.raises(UnsupportedFormat):
        reader.sheet_meta(corrupt_xlsx, "sh")


# ---------------------------------------------------------------------------
# analyzer edge cases
# ---------------------------------------------------------------------------


def test_register_empty_rows_then_count():
    sd = SheetData(columns=("a", "b"), rows=())
    with Analyzer() as az:
        az.register("t", sd)
        result = az.query("SELECT count(*) AS n FROM t")
        assert result.rows == ((0,),)


def test_cast_operator_not_converted():
    sd = SheetData(columns=("s",), rows=(("5",),))
    with Analyzer() as az:
        az.register("t", sd)
        # ::INTEGER cast must NOT be mangled into a $param by _to_duckdb_sql
        result = az.query("SELECT s::INTEGER AS x FROM t")
        assert result.rows == ((5,),)


# ---------------------------------------------------------------------------
# writer edge cases
# ---------------------------------------------------------------------------


def test_empty_sheets_dict_raises(tmp_path: Path):
    with pytest.raises(WriteError):
        writer.write_workbook(tmp_path / "o.xlsx", {})


def test_overwrite_existing_target(tmp_path: Path):
    target = tmp_path / "out.xlsx"
    writer.write_workbook(target, {"s": SheetData(columns=("a",), rows=((1,),))})
    writer.write_workbook(
        target, {"s": SheetData(columns=("a",), rows=((2,), (3,)))}
    )
    back = reader.read_sheet(target, "s")
    assert back.rows == ((2,), (3,))  # second write replaced the first


def test_replace_retry_recovers(tmp_path: Path, monkeypatch):
    import excelops.backends.writer as w

    monkeypatch.setattr(w, "_REPLACE_BACKOFF", 0.0)
    calls = {"n": 0}
    real_replace = w.os.replace

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError(5, "transient lock")
        return real_replace(src, dst)

    monkeypatch.setattr(w.os, "replace", flaky)
    sd = SheetData(columns=("a",), rows=((1,),))
    result = writer.write_workbook(tmp_path / "out.xlsx", {"s": sd})
    assert calls["n"] == 2  # failed once, then succeeded on retry
    assert result.rows_written == 1
    assert [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")] == []


def test_ragged_user_sheet_data_rejected(tmp_path: Path):
    bad = SheetData(columns=("a", "b"), rows=((1, 2), (3,)))  # last row too short
    with pytest.raises(WriteError):
        writer.write_workbook(tmp_path / "o.xlsx", {"s": bad})


# ---------------------------------------------------------------------------
# package public API (L1)
# ---------------------------------------------------------------------------


def test_top_level_exports():
    for name in (
        "read_sheet",
        "list_sheets",
        "sheet_meta",
        "write_workbook",
        "Analyzer",
        "SheetData",
        "SheetMeta",
        "WriteResult",
        "ExcelOpsError",
        "ReadError",
        "WriteError",
    ):
        assert hasattr(excelops, name), f"excelops.{name} not exported"
    assert "Analyzer" in excelops.__all__
