"""Database connector + tools against a real in-memory/temp SQLite database.

Proves the core safety guarantee: db_query is physically read-only (writes are
rolled back), and db_execute is gated by read-only mode. Also covers the
row cap, query timeout, and Redis command gate on db_query.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from serverops.connectors.base import AsyncConnector, HealthStatus
from serverops.connectors.database import DatabaseConnector
from serverops.errors import SafetyError, ServerOpsError
from serverops.models import ServerOpsConfig, SQLiteProfile
from serverops.registry import ConnectorRegistry
from serverops.tools import db_tools


class FakeMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self, fn=None, **_):
        if callable(fn):
            self.tools[fn.__name__] = fn
            return fn

        def deco(f):
            self.tools[f.__name__] = f
            return f

        return deco

    def custom_route(self, *_a, **_k):
        def deco(f):
            return f

        return deco


def _db_registry(tmp_path, *, read_only=False, settings_read_only=False, settings_extra=None):
    url = f"sqlite:///{tmp_path}/t.db"
    settings = {"read_only": settings_read_only}
    if settings_extra:
        settings.update(settings_extra)
    cfg = ServerOpsConfig.model_validate(
        {
            "settings": settings,
            "connections": {"db": {"kind": "sqlite", "url": url, "read_only": read_only}},
        }
    )
    reg = ConnectorRegistry(cfg)
    from serverops.connectors import database as db_module

    reg._build = lambda name, profile: db_module.build(name, profile)  # type: ignore[method-assign]
    return reg


# ---------------------------------------------------------------------------
# Connector-level
# ---------------------------------------------------------------------------


async def test_roundtrip_create_insert_select(tmp_path) -> None:
    conn = DatabaseConnector("db", SQLiteProfile(url=f"sqlite:///{tmp_path}/t.db"))
    await conn.connect()
    await conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
    await conn.execute(
        "INSERT INTO users (id, name) VALUES (:id, :name)", {"id": 1, "name": "alice"}
    )
    columns, rows, _truncated = await conn.query("SELECT * FROM users")
    assert columns == ["id", "name"]
    assert rows == [[1, "alice"]]
    await conn.close()


async def test_query_is_physically_readonly(tmp_path) -> None:
    conn = DatabaseConnector("db", SQLiteProfile(url=f"sqlite:///{tmp_path}/t.db"))
    await conn.connect()
    await conn.execute("CREATE TABLE t (x INTEGER)")
    # attempt a write through the read-only query path
    await conn.query("INSERT INTO t (x) VALUES (1)")
    # verify nothing persisted
    _, rows, _truncated = await conn.query("SELECT count(*) FROM t")
    assert rows == [[0]]
    await conn.close()


async def test_health_after_connect(tmp_path) -> None:
    conn = DatabaseConnector("db", SQLiteProfile(url=f"sqlite:///{tmp_path}/t.db"))
    await conn.connect()
    status = await conn.health()
    assert status.healthy is True
    await conn.close()


async def test_query_respects_limit_and_reports_truncated(tmp_path) -> None:
    conn = DatabaseConnector("db", SQLiteProfile(url=f"sqlite:///{tmp_path}/t.db"))
    await conn.connect()
    await conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY)")
    for i in range(1, 11):
        await conn.execute("INSERT INTO items (id) VALUES (:id)", {"id": i})
    columns, rows, truncated = await conn.query("SELECT * FROM items", limit=3)
    assert columns == ["id"]
    assert len(rows) == 3
    assert rows == [[1], [2], [3]]
    assert truncated is True
    columns, rows, truncated = await conn.query("SELECT * FROM items", limit=50)
    assert len(rows) == 10
    assert truncated is False
    await conn.close()


async def test_query_non_rows_result_returns_truncated_false(tmp_path) -> None:
    conn = DatabaseConnector("db", SQLiteProfile(url=f"sqlite:///{tmp_path}/t.db"))
    await conn.connect()
    await conn.execute("CREATE TABLE t (x INTEGER)")
    # non-rowset statement: no fetchmany on a result without rows (no AttributeError)
    columns, rows, truncated = await conn.query("INSERT INTO t (x) VALUES (1)")
    assert columns == []
    assert rows == []
    assert truncated is False
    await conn.close()


# ---------------------------------------------------------------------------
# Tool-level
# ---------------------------------------------------------------------------


async def test_tool_execute_then_query(tmp_path) -> None:
    reg = _db_registry(tmp_path)
    mcp = FakeMCP()
    db_tools.register(mcp, reg)
    await mcp.tools["db_execute"](
        "db", "CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)"
    )
    await mcp.tools["db_execute"](
        "db", "INSERT INTO notes (id, body) VALUES (:id, :body)", {"id": 1, "body": "hi"}
    )
    result = await mcp.tools["db_query"]("db", "SELECT * FROM notes")
    assert result["rows"] == [[1, "hi"]]
    assert result["columns"] == ["id", "body"]


async def test_tool_query_readonly_blocks_persistence(tmp_path) -> None:
    reg = _db_registry(tmp_path)
    mcp = FakeMCP()
    db_tools.register(mcp, reg)
    await mcp.tools["db_execute"]("db", "CREATE TABLE t (x INTEGER)")
    # write attempted via the (read-only) query tool
    await mcp.tools["db_query"]("db", "INSERT INTO t (x) VALUES (1)")
    count = await mcp.tools["db_query"]("db", "SELECT count(*) FROM t")
    assert count["rows"] == [[0]]


async def test_tool_execute_blocked_when_readonly(tmp_path) -> None:
    reg = _db_registry(tmp_path, settings_read_only=True)
    mcp = FakeMCP()
    db_tools.register(mcp, reg)
    with pytest.raises(SafetyError):
        await mcp.tools["db_execute"]("db", "CREATE TABLE t (x INTEGER)")


async def test_tool_tables_and_schema(tmp_path) -> None:
    reg = _db_registry(tmp_path)
    mcp = FakeMCP()
    db_tools.register(mcp, reg)
    await mcp.tools["db_execute"]("db", "CREATE TABLE things (id INTEGER PRIMARY KEY, w REAL)")
    tables = await mcp.tools["db_tables"]("db")
    assert tables == {"tables": ["things"]}
    schema = await mcp.tools["db_schema"]("db", "things")
    names = [c["name"] for c in schema["columns"]]
    assert names == ["id", "w"]


async def test_db_tool_rejects_non_db_connection(tmp_path) -> None:
    cfg = ServerOpsConfig.model_validate(
        {"connections": {"web1": {"kind": "ssh", "host": "h", "user": "u"}}}
    )
    reg = ConnectorRegistry(cfg)
    mcp = FakeMCP()
    db_tools.register(mcp, reg)
    with pytest.raises(ServerOpsError):
        await mcp.tools["db_query"]("web1", "SELECT 1")


# ---------------------------------------------------------------------------
# Row cap (max_rows)
# ---------------------------------------------------------------------------


async def test_tool_query_reports_truncated_and_max_rows(tmp_path) -> None:
    reg = _db_registry(tmp_path)
    mcp = FakeMCP()
    db_tools.register(mcp, reg)
    await mcp.tools["db_execute"]("db", "CREATE TABLE t (id INTEGER PRIMARY KEY)")
    for i in range(1, 11):
        await mcp.tools["db_execute"]("db", "INSERT INTO t (id) VALUES (:id)", {"id": i})
    result = await mcp.tools["db_query"]("db", "SELECT * FROM t", max_rows=3)
    assert result["max_rows"] == 3
    assert result["truncated"] is True
    assert result["row_count"] == 3
    assert result["rows"] == [[1], [2], [3]]
    full = await mcp.tools["db_query"]("db", "SELECT * FROM t", max_rows=50)
    assert full["truncated"] is False
    assert full["row_count"] == 10


async def test_tool_query_max_rows_out_of_range_rejected(tmp_path) -> None:
    reg = _db_registry(tmp_path)
    mcp = FakeMCP()
    db_tools.register(mcp, reg)
    with pytest.raises(ServerOpsError):
        await mcp.tools["db_query"]("db", "SELECT 1", max_rows=0)
    with pytest.raises(ServerOpsError):
        await mcp.tools["db_query"]("db", "SELECT 1", max_rows=9999)


async def test_tool_query_default_max_rows_from_settings(tmp_path) -> None:
    reg = _db_registry(tmp_path, settings_extra={"query_max_rows": 5})
    mcp = FakeMCP()
    db_tools.register(mcp, reg)
    await mcp.tools["db_execute"]("db", "CREATE TABLE t (id INTEGER PRIMARY KEY)")
    for i in range(1, 11):
        await mcp.tools["db_execute"]("db", "INSERT INTO t (id) VALUES (:id)", {"id": i})
    result = await mcp.tools["db_query"]("db", "SELECT * FROM t")
    assert result["max_rows"] == 5
    assert result["truncated"] is True
    assert result["row_count"] == 5


# ---------------------------------------------------------------------------
# Timeout + Redis command gate + Elasticsearch guard
# ---------------------------------------------------------------------------


class StubQueryConnector(AsyncConnector):
    """Connector stub whose query() never finishes within a test timeout."""

    kind = "database"

    async def connect(self) -> None:
        return None

    async def health(self) -> HealthStatus:
        return HealthStatus(True, "stub")

    async def close(self) -> None:
        return None

    async def query(self, sql, params=None, limit=None):
        await asyncio.sleep(5)
        return ([], [], False)


class StubRedisConnector(AsyncConnector):
    """Redis connector stub that records executed commands."""

    kind = "database"

    def __init__(self, name, profile):
        super().__init__(name, profile)
        self.commands: list[tuple[str, ...]] = []

    async def connect(self) -> None:
        return None

    async def health(self) -> HealthStatus:
        return HealthStatus(True, "stub")

    async def close(self) -> None:
        return None

    async def redis_command(self, *args):
        self.commands.append(args)
        return "stub-ok"


def _redis_registry(tmp_path, *, read_only=False):
    cfg = ServerOpsConfig.model_validate(
        {
            "settings": {"read_only": read_only},
            "connections": {"r": {"kind": "redis", "url": "redis://localhost"}},
        }
    )
    reg = ConnectorRegistry(cfg)
    stub = StubRedisConnector("r", cfg.connections["r"])
    reg._build = lambda name, profile: stub  # type: ignore[method-assign]
    return reg, stub


async def test_tool_query_timeout_raises_audits_and_invalidates(tmp_path) -> None:
    reg = _db_registry(tmp_path, settings_extra={"audit_log": str(tmp_path / "audit.jsonl")})
    reg._build = lambda name, profile: StubQueryConnector(name, profile)  # type: ignore[method-assign]
    mcp = FakeMCP()
    db_tools.register(mcp, reg)
    with pytest.raises(ServerOpsError, match="timed out"):
        await mcp.tools["db_query"]("db", "SELECT 1", timeout_s=0.05)
    assert reg._cache == {}  # stuck connector dropped, next call reconnects
    lines = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert lines, "timeout must be audited"
    assert json.loads(lines[-1])["status"] == "timeout"
    # a retry after invalidation rebuilds the connector and succeeds
    from serverops.connectors import database as db_module

    reg._build = lambda name, profile: db_module.build(name, profile)  # type: ignore[method-assign]
    retry = await mcp.tools["db_query"]("db", "SELECT 1")
    assert retry["rows"] == [[1]]


async def test_tool_query_timeout_rejects_nonpositive(tmp_path) -> None:
    reg = _db_registry(tmp_path)
    mcp = FakeMCP()
    db_tools.register(mcp, reg)
    with pytest.raises(ServerOpsError, match="timeout"):
        await mcp.tools["db_query"]("db", "SELECT 1", timeout_s=0)


async def test_tool_redis_write_blocked_when_readonly(tmp_path) -> None:
    reg, stub = _redis_registry(tmp_path, read_only=True)
    mcp = FakeMCP()
    db_tools.register(mcp, reg)
    with pytest.raises(SafetyError):
        await mcp.tools["db_query"]("r", "SET k v")
    assert stub.commands == []  # gate fired before the connector was touched


async def test_tool_redis_read_passes_when_readonly(tmp_path) -> None:
    reg, stub = _redis_registry(tmp_path, read_only=True)
    mcp = FakeMCP()
    db_tools.register(mcp, reg)
    result = await mcp.tools["db_query"]("r", "GET k")
    assert result == {"value": "stub-ok"}
    assert stub.commands == [("GET", "k")]


async def test_tool_query_elasticsearch_rejected(tmp_path) -> None:
    cfg = ServerOpsConfig.model_validate(
        {"connections": {"es": {"kind": "elasticsearch", "url": "http://localhost:9200"}}}
    )
    reg = ConnectorRegistry(cfg)
    mcp = FakeMCP()
    db_tools.register(mcp, reg)
    with pytest.raises(ServerOpsError, match="es_search"):
        await mcp.tools["db_query"]("es", "SELECT 1")
