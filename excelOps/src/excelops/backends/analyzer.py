"""Embedded DuckDB analyzer (design D3 / D6).

A session-scoped context manager. ``duckdb`` is imported lazily on enter (so
``import excelops`` works without the ``[duckdb]`` extra); the raw connection is
never exposed. ``SheetData`` is registered zero-copy via a pyarrow Table, and
query results come back as ``SheetData``.

Named parameters use the spec's ``:name`` style; duckdb natively wants
``$name``, so ``_to_duckdb_sql`` adapts while skipping single-quoted string
literals and the ``::`` cast operator.
"""

from __future__ import annotations

from ..errors import AnalyzeError, MissingDependency
from .models import SheetData

__all__ = ["Analyzer"]

_INSTALL_HINT = "pip install 'excelops[duckdb]'"


def _to_duckdb_sql(sql: str) -> str:
    """Convert ``:name`` params to duckdb's ``$name`` form.

    Skips single-quoted string literals and the ``::`` cast operator so only
    real named params are rewritten. (Does not parse line/block comments or
    double-quoted identifiers — keep SQL simple, per Phase 1 scope.)
    """
    out: list[str] = []
    i = 0
    n = len(sql)
    in_str = False
    while i < n:
        ch = sql[i]
        if ch == "'":
            out.append(ch)
            in_str = not in_str
            i += 1
            continue
        if not in_str and ch == ":":
            if i + 1 < n and sql[i + 1] == ":":
                # cast operator ::TYPE — emit as-is
                out.append("::")
                i += 2
                continue
            j = i + 1
            while j < n and (sql[j].isalnum() or sql[j] == "_"):
                j += 1
            if j > i + 1:  # :name found
                out.append("$")
                out.append(sql[i + 1 : j])
                i = j
                continue
        out.append(ch)
        i += 1
    return "".join(out)


class Analyzer:
    """Session-scoped DuckDB analyzer.

    Use as a context manager::

        with Analyzer() as az:
            az.register("orders", sd)
            az.query("SELECT region, sum(amount) AS total FROM orders GROUP BY region")

    ``database`` defaults to an in-memory DB (``:memory:``); pass a path for a
    file-backed DB. Only ``register`` / ``query`` / ``close`` are public.
    """

    def __init__(self, database: str = ":memory:"):
        self._database = database
        self._duckdb = None
        self._conn = None
        self._closed = False

    def __enter__(self) -> Analyzer:
        try:
            import duckdb
        except ImportError as e:
            raise MissingDependency(
                f"duckdb is required for analysis; install it with: {_INSTALL_HINT}"
            ) from e
        self._duckdb = duckdb
        try:
            self._conn = duckdb.connect(self._database)
        except duckdb.Error as e:
            raise AnalyzeError(f"failed to open DuckDB session: {e}") from e
        self._closed = False
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def register(self, name: str, sheet_data: SheetData) -> None:
        """Register ``sheet_data`` as a queryable table ``name`` (replace semantics)."""
        self._ensure_open()
        try:
            import pyarrow as pa
        except ImportError as e:
            raise MissingDependency(
                f"pyarrow is required for analysis; install it with: {_INSTALL_HINT}"
            ) from e
        columns = sheet_data.columns
        rows = sheet_data.rows
        # Column-oriented build lets pyarrow infer types natively (date stays
        # date32, etc.) — no implicit stringification.
        table = pa.table({col: [row[i] for row in rows] for i, col in enumerate(columns)})
        # duckdb.register replaces any existing view of the same name (CREATE OR
        # REPLACE semantics) — re-registering never raises.
        self._conn.register(name, table)

    def query(self, sql: str, params: dict | None = None) -> SheetData:
        """Run ``sql`` (``:name`` params bound from ``params``); return a SheetData."""
        self._ensure_open()
        duckdb = self._duckdb
        assert duckdb is not None  # _ensure_open guarantees __enter__ ran
        adapted = _to_duckdb_sql(sql)
        try:
            result = (
                self._conn.execute(adapted, params)
                if params
                else self._conn.execute(adapted)
            )
        except duckdb.Error as e:
            raise AnalyzeError(f"SQL error: {e}") from e
        arrow = result.to_arrow_table()
        columns = tuple(arrow.column_names)
        pylist = arrow.to_pylist()
        rows = tuple(tuple(row[col] for col in columns) for row in pylist)
        return SheetData(columns=columns, rows=rows)

    def close(self) -> None:
        """Close the DuckDB session. Further register/query raises AnalyzeError."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None
        self._closed = True

    def _ensure_open(self) -> None:
        if self._closed or self._conn is None:
            raise AnalyzeError("analyzer session is closed")
