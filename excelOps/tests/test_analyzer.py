"""Tests for the embedded-DuckDB analyzer (backends/analyzer.py).

Covers the excel-analyze spec: register SheetData as a queryable table
(replace semantics), parameterized SQL with ``:name`` placeholders, result ->
SheetData, date fidelity, session lifecycle, restricted public surface, typed
errors (MissingDependency / AnalyzeError).

Note: duckdb natively uses ``$name`` params; the analyzer accepts the
spec-mandated ``:name`` style and adapts internally.
"""

from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

import pytest

from excelops.backends.analyzer import Analyzer
from excelops.backends.models import SheetData
from excelops.errors import AnalyzeError, MissingDependency


@pytest.fixture
def orders() -> SheetData:
    return SheetData(
        columns=("region", "amount"),
        rows=(("east", 100), ("west", 200), ("east", 50)),
    )


# ---------------------------------------------------------------------------
# register + query (4.2 / 4.3)
# ---------------------------------------------------------------------------


def test_register_then_count(orders: SheetData):
    with Analyzer() as az:
        az.register("orders", orders)
        result = az.query("SELECT count(*) AS n FROM orders")
        assert result.columns == ("n",)
        assert result.rows == ((3,),)


def test_register_replaces_same_name(orders: SheetData):
    other = SheetData(columns=("region", "amount"), rows=(("north", 7),))
    with Analyzer() as az:
        az.register("orders", orders)
        az.register("orders", other)  # CREATE OR REPLACE semantics
        result = az.query("SELECT count(*) AS n FROM orders")
        assert result.rows == ((1,),)
        assert az.query("SELECT region FROM orders").rows == (("north",),)


def test_query_named_param_filter(orders: SheetData):
    with Analyzer() as az:
        az.register("orders", orders)
        result = az.query(
            "SELECT * FROM orders WHERE region = :r", {"r": "east"}
        )
        assert result.columns == ("region", "amount")
        assert result.rows == (("east", 100), ("east", 50))


def test_query_result_shape(orders: SheetData):
    with Analyzer() as az:
        az.register("orders", orders)
        result = az.query(
            "SELECT region, sum(amount) AS total "
            "FROM orders GROUP BY region ORDER BY region"
        )
        assert result.columns == ("region", "total")
        assert result.rows == (("east", 150), ("west", 200))


def test_query_date_fidelity():
    sd = SheetData(
        columns=("created_at",),
        rows=((date(2026, 1, 1),), (date(2026, 1, 2),)),
    )
    with Analyzer() as az:
        az.register("d", sd)
        result = az.query("SELECT created_at FROM d ORDER BY created_at")
        assert all(isinstance(v, (date, datetime)) for (v,) in result.rows)
        assert not any(isinstance(v, str) for (v,) in result.rows)


def test_named_param_inside_string_literal_not_converted(orders: SheetData):
    # ":r" inside a string literal must NOT be treated as a parameter.
    with Analyzer() as az:
        az.register("orders", orders)
        result = az.query("SELECT ':r' AS lit FROM orders WHERE region = :r", {"r": "east"})
        assert result.rows[0] == (":r",)


# ---------------------------------------------------------------------------
# lifecycle (4.1 / 4.4)
# ---------------------------------------------------------------------------


def test_query_after_exit_raises(orders: SheetData):
    with Analyzer() as az:
        az.register("orders", orders)
    with pytest.raises(AnalyzeError):
        az.query("SELECT 1")


def test_register_after_exit_raises(orders: SheetData):
    with Analyzer() as az:
        pass
    with pytest.raises(AnalyzeError):
        az.register("orders", orders)


def test_exit_closes_connection(orders: SheetData):
    az = Analyzer()
    with az:
        az.register("orders", orders)
    assert az._conn is None


def test_no_connection_in_public_api():
    with Analyzer() as az:
        exposed = [name for name in dir(az) if not name.startswith("_")]
        assert not any(
            "conn" in name.lower() or "cursor" in name.lower() for name in exposed
        )


def test_file_database(tmp_path: Path, orders: SheetData):
    db = tmp_path / "a.duckdb"
    with Analyzer(database=str(db)) as az:
        az.register("orders", orders)
        assert az.query("SELECT count(*) AS n FROM orders").rows == ((3,),)
    assert db.exists()


# ---------------------------------------------------------------------------
# typed errors (4.1 / 4.3)
# ---------------------------------------------------------------------------


def test_missing_duckdb_raises_missing_dependency(monkeypatch):
    # Simulate duckdb not installed: import duckdb -> ImportError.
    monkeypatch.setitem(sys.modules, "duckdb", None)
    with pytest.raises(MissingDependency) as ei, Analyzer():
        pass
    assert "excelops[duckdb]" in str(ei.value)


def test_invalid_sql_raises_analyze_error(orders: SheetData):
    with Analyzer() as az:
        az.register("orders", orders)
        with pytest.raises(AnalyzeError):
            az.query("SELECT FROMM orders")
