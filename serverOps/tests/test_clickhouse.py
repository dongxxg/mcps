"""ClickHouse connector + tools.

No real ClickHouse server is required: ``clickhouse_connect`` is replaced in
``sys.modules`` with a fake that records the connect kwargs and the SQL/params
sent to ``query``. The real driver is never imported.

Core guarantee under test: ClickHouse is **query-only by design** — ``db_execute``
is blocked, and ``db_query`` rejects any statement whose leading keyword is not a
read (ClickHouse has no transaction/rollback, so the rollback trick used for the
SQLAlchemy backends does not apply).
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from serverops.connectors.database import (
    DatabaseConnector,
    _ch_bind_params,
    _ch_params_from_url,
    _require_clickhouse_read,
)
from serverops.errors import ServerOpsError
from serverops.models import ClickHouseProfile, ServerOpsConfig
from serverops.registry import ConnectorRegistry
from serverops.tools import db_tools

# ---------------------------------------------------------------------------
# Fake clickhouse-connect driver
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, column_names: list[str], result_rows: list[list[Any]]) -> None:
        self.column_names = tuple(column_names)
        self.result_rows = [tuple(r) for r in result_rows]


class _FakeCHClient:
    def __init__(self) -> None:
        self.connect_kwargs: dict[str, Any] | None = None
        self.queries: list[tuple[str, dict | None]] = []
        self.closed = False
        self._responses: dict[str, _FakeResult] = {}

    def set(self, sql: str, column_names: list[str], result_rows: list[list[Any]]) -> None:
        self._responses[sql] = _FakeResult(column_names, result_rows)

    def query(self, sql: str, parameters: dict | None = None, **_kw: Any) -> _FakeResult:
        self.queries.append((sql, parameters))
        if sql in self._responses:
            return self._responses[sql]
        if sql == "SELECT 1":
            return _FakeResult(["1"], [[1]])
        if sql == "SHOW TABLES":
            return _FakeResult(["name"], [["events"], ["users"]])
        if sql.startswith("DESCRIBE TABLE"):
            return _FakeResult(
                ["name", "type", "default_type", "default_expression"],
                [
                    ["id", "UInt64", "DEFAULT", ""],
                    ["email", "Nullable(String)", "DEFAULT", ""],
                    ["created_at", "DateTime", "DEFAULT", "now()"],
                ],
            )
        return _FakeResult([], [])

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_ch(monkeypatch: pytest.MonkeyPatch) -> _FakeCHClient:
    """Inject a fake ``clickhouse_connect`` module so ``connect()`` never hits the network."""
    client = _FakeCHClient()
    mod = types.ModuleType("clickhouse_connect")

    def get_client(**kwargs: Any) -> _FakeCHClient:
        client.connect_kwargs = kwargs
        return client

    mod.get_client = get_client
    monkeypatch.setitem(sys.modules, "clickhouse_connect", mod)
    return client


async def _ck(url: str = "clickhouse://localhost") -> DatabaseConnector:
    conn = DatabaseConnector("ck", ClickHouseProfile(url=url))
    await conn.connect()
    return conn


def _ck_registry(url: str = "clickhouse://localhost") -> ConnectorRegistry:
    cfg = ServerOpsConfig.model_validate(
        {"connections": {"ck": {"kind": "clickhouse", "url": url}}}
    )
    reg = ConnectorRegistry(cfg)
    from serverops.connectors import database as db_module

    reg._build = lambda name, profile: db_module.build(name, profile)  # type: ignore[method-assign]
    return reg


# ---------------------------------------------------------------------------
# URL parsing (pure function, no fake needed)
# ---------------------------------------------------------------------------


def test_url_insecure_default_port() -> None:
    assert _ch_params_from_url("clickhouse://localhost") == {
        "host": "localhost",
        "port": 8123,
        "username": "default",
        "password": "",
        "database": None,
        "secure": False,
    }


def test_url_secure_schemes_default_8443() -> None:
    for scheme in ("clickhouse+https", "clickhouses", "clickhouse+secure"):
        p = _ch_params_from_url(f"{scheme}://localhost")
        assert p["secure"] is True, scheme
        assert p["port"] == 8443, scheme


def test_url_explicit_port_wins() -> None:
    p = _ch_params_from_url("clickhouse+https://localhost:9000")
    assert p["secure"] is True
    assert p["port"] == 9000


def test_url_user_pass_database() -> None:
    p = _ch_params_from_url("clickhouse://bob:s3cret@ch.host:8123/analytics")
    assert p == {
        "host": "ch.host",
        "port": 8123,
        "username": "bob",
        "password": "s3cret",
        "database": "analytics",
        "secure": False,
    }


# ---------------------------------------------------------------------------
# Read-keyword guard (pure function)
# ---------------------------------------------------------------------------


def test_read_guard_accepts_read_statements() -> None:
    for sql in [
        "SELECT 1",
        "WITH x AS (SELECT 1) SELECT * FROM x",
        "SHOW TABLES",
        "DESCRIBE TABLE t",
        "DESC t",
        "EXPLAIN SELECT 1",
        "EXISTS(SELECT 1)",
        "/* hint */ SELECT 1",
        "-- a comment\nSELECT 1",
        "; SELECT 1",
        "(SELECT 1)",
        "   \n  SELECT 1",
    ]:
        _require_clickhouse_read(sql)  # must not raise


def test_read_guard_rejects_write_statements() -> None:
    for sql in [
        "INSERT INTO t VALUES (1)",
        "CREATE TABLE t (x UInt8)",
        "DROP TABLE t",
        "ALTER TABLE t ADD COLUMN y UInt8",
        "TRUNCATE TABLE t",
        "DELETE FROM t",
        "UPDATE t SET x = 1",
        "OPTIMIZE TABLE t FINAL",
        "SYSTEM FLUSH LOGS",
        "RENAME TABLE a TO b",
    ]:
        with pytest.raises(ServerOpsError):
            _require_clickhouse_read(sql)


# ---------------------------------------------------------------------------
# Param binding translation (pure function)
# ---------------------------------------------------------------------------


def test_bind_params_none_when_no_params() -> None:
    sql, params = _ch_bind_params("SELECT :id WHERE p = '100%'", None)
    # untouched: literal % stays safe because the driver won't %-format
    assert params is None
    assert sql == "SELECT :id WHERE p = '100%'"


def test_bind_params_translates_and_preserves_casts() -> None:
    sql, params = _ch_bind_params(
        "SELECT toString(1::Int) = :val AND 2::Int = 2", {"val": 1}
    )
    assert sql == "SELECT toString(1::Int) = %(val)s AND 2::Int = 2"
    assert params == {"val": 1}


# ---------------------------------------------------------------------------
# Profile / model
# ---------------------------------------------------------------------------


def test_clickhouse_profile_routes_through_union() -> None:
    cfg = ServerOpsConfig.model_validate(
        {"connections": {"ck": {"kind": "clickhouse", "url": "clickhouse://localhost"}}}
    )
    assert isinstance(cfg.connections["ck"], ClickHouseProfile)
    assert cfg.connections["ck"].kind == "clickhouse"


# ---------------------------------------------------------------------------
# Connector-level
# ---------------------------------------------------------------------------


async def test_connect_passes_url_params_and_close(fake_ch: _FakeCHClient) -> None:
    conn = await _ck("clickhouse://bob:s3cret@ch.host:8123/analytics")
    assert fake_ch.connect_kwargs == {
        "host": "ch.host",
        "port": 8123,
        "username": "bob",
        "password": "s3cret",
        "database": "analytics",
        "secure": False,
    }
    await conn.close()
    assert fake_ch.closed is True


async def test_query_returns_columns_and_rows(fake_ch: _FakeCHClient) -> None:
    conn = await _ck()
    fake_ch.set("SELECT count(*) AS n FROM events", ["n"], [[42]])
    cols, rows = await conn.query("SELECT count(*) AS n FROM events")
    assert cols == ["n"]
    assert rows == [[42]]
    await conn.close()


async def test_query_translates_params_before_send(fake_ch: _FakeCHClient) -> None:
    conn = await _ck()
    fake_ch.set("SELECT id FROM t WHERE id = %(i)s", ["id"], [[5]])
    await conn.query("SELECT id FROM t WHERE id = :i", {"i": 5})
    sent_sql, sent_params = fake_ch.queries[-1]
    assert sent_sql == "SELECT id FROM t WHERE id = %(i)s"
    assert sent_params == {"i": 5}
    await conn.close()


async def test_query_rejects_write_and_sends_nothing(fake_ch: _FakeCHClient) -> None:
    conn = await _ck()
    with pytest.raises(ServerOpsError):
        await conn.query("INSERT INTO t VALUES (1)")
    assert fake_ch.queries == []  # guard fired before contacting ClickHouse
    await conn.close()


async def test_execute_always_raises(fake_ch: _FakeCHClient) -> None:
    conn = await _ck()
    with pytest.raises(ServerOpsError):
        await conn.execute("INSERT INTO t VALUES (1)")
    await conn.close()


async def test_health_runs_select_one(fake_ch: _FakeCHClient) -> None:
    conn = await _ck()
    status = await conn.health()
    assert status.healthy is True
    assert fake_ch.queries[-1] == ("SELECT 1", None)
    await conn.close()


async def test_tables_and_schema(fake_ch: _FakeCHClient) -> None:
    conn = await _ck()
    assert await conn.tables() == ["events", "users"]
    schema = await conn.schema("users")
    assert [c["name"] for c in schema] == ["id", "email", "created_at"]
    email = next(c for c in schema if c["name"] == "email")
    assert email["nullable"] is True  # Nullable(String) detected
    created = next(c for c in schema if c["name"] == "created_at")
    assert created["default"] == "now()"
    await conn.close()


# ---------------------------------------------------------------------------
# Tool-level
# ---------------------------------------------------------------------------


async def test_tool_query_tables_schema(fake_ch: _FakeCHClient, fake_mcp) -> None:
    reg = _ck_registry()
    db_tools.register(fake_mcp, reg)
    fake_ch.set("SELECT 1", ["1"], [[1]])
    result = await fake_mcp.tools["db_query"]("ck", "SELECT 1")
    assert result == {"columns": ["1"], "rows": [[1]], "row_count": 1}
    tables = await fake_mcp.tools["db_tables"]("ck")
    assert tables == {"tables": ["events", "users"]}
    schema = await fake_mcp.tools["db_schema"]("ck", "users")
    assert [c["name"] for c in schema["columns"]] == ["id", "email", "created_at"]


async def test_tool_execute_blocked_for_clickhouse(fake_ch: _FakeCHClient, fake_mcp) -> None:
    reg = _ck_registry()
    db_tools.register(fake_mcp, reg)
    with pytest.raises(ServerOpsError):
        await fake_mcp.tools["db_execute"]("ck", "CREATE TABLE t (x UInt8) ENGINE=Memory")
    # a write sneaked through db_query is also rejected by the read-keyword guard
    with pytest.raises(ServerOpsError):
        await fake_mcp.tools["db_query"]("ck", "DROP TABLE t")
    assert fake_ch.queries == []
