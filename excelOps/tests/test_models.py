"""Tests for the shared data model (backends/models.py).

``SheetData`` is the single spine type crossing reader → analyzer → writer.
It MUST be immutable (frozen) and hold tuples, so it is hashable, JSON-friendly,
and never silently mutated by a downstream engine.
"""

from __future__ import annotations

import dataclasses
from datetime import date
from pathlib import Path

import pytest

from excelops.backends.models import SheetData, SheetMeta, WriteResult


class TestSheetData:
    def test_is_frozen_dataclass(self):
        assert dataclasses.is_dataclass(SheetData)
        sd = SheetData(columns=("a", "b"), rows=((1, 2),))
        with pytest.raises(dataclasses.FrozenInstanceError):
            sd.columns = ("x",)  # type: ignore[misc]

    def test_fields_are_columns_and_rows(self):
        names = {f.name for f in dataclasses.fields(SheetData)}
        assert names == {"columns", "rows"}

    def test_accepts_and_keeps_tuples(self):
        sd = SheetData(columns=("a", "b"), rows=((1, 2), (3, 4)))
        assert sd.columns == ("a", "b")
        assert sd.rows == ((1, 2), (3, 4))

    def test_value_equality(self):
        a = SheetData(columns=("a",), rows=((1,),))
        b = SheetData(columns=("a",), rows=((1,),))
        assert a == b

    def test_preserves_native_cell_types(self):
        # date must stay a date, not be coerced to a string/serial.
        sd = SheetData(columns=("d",), rows=((date(2026, 1, 1),),))
        assert isinstance(sd.rows[0][0], date)

    def test_empty_rows_allowed(self):
        sd = SheetData(columns=("a", "b"), rows=())
        assert sd.rows == ()

    def test_is_hashable(self):
        # frozen + tuple fields => hashable, safe as dict value / cache key.
        sd = SheetData(columns=("a",), rows=((1,),))
        assert hash(sd) == hash(SheetData(columns=("a",), rows=((1,),)))


class TestSheetMeta:
    def test_fields(self):
        meta = SheetMeta(max_row=5, max_col=3)
        assert meta.max_row == 5
        assert meta.max_col == 3


class TestWriteResult:
    def test_fields(self):
        wr = WriteResult(
            path=Path("/tmp/out.xlsx"),
            bytes_written=1024,
            rows_written=10,
            source_ref="orders",
        )
        assert wr.path == Path("/tmp/out.xlsx")
        assert wr.bytes_written == 1024
        assert wr.rows_written == 10
        assert wr.source_ref == "orders"

    def test_source_ref_defaults_none(self):
        wr = WriteResult(path=Path("/tmp/o.xlsx"), bytes_written=1, rows_written=0)
        assert wr.source_ref is None
