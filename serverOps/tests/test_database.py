"""Database connector + tools against a real in-memory/temp SQLite database.

Proves the core safety guarantee: db_query is physically read-only (writes are
rolled back), and db_execute is gated by read-only mode.
"""

from __future__ import annotations

from typing import Any

import pytest

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


def _db_registry(tmp_path, *, read_only=False, settings_read_only=False):
    url = f"sqlite:///{tmp_path}/t.db"
    cfg = ServerOpsConfig.model_validate(
        {
            "settings": {"read_only": settings_read_only},
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
    columns, rows = await conn.query("SELECT * FROM users")
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
    _, rows = await conn.query("SELECT count(*) FROM t")
    assert rows == [[0]]
    await conn.close()


async def test_health_after_connect(tmp_path) -> None:
    conn = DatabaseConnector("db", SQLiteProfile(url=f"sqlite:///{tmp_path}/t.db"))
    await conn.connect()
    status = await conn.health()
    assert status.healthy is True
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
