"""Database tools: db_query (read-only) / db_execute (gated) / db_tables / db_schema.

Named parameters are used for SQL substitution (cross-driver safe):
``sql="SELECT * FROM users WHERE id = :id"``, ``params={"id": 1}``.
"""

from __future__ import annotations

from ..errors import ServerOpsError
from ..models import DATABASE_KINDS
from ._common import redacted


def register(mcp, registry) -> None:
    def _require_db(connection: str):
        profile = registry.get_profile(connection)
        if profile.kind not in DATABASE_KINDS:
            raise ServerOpsError(
                f"Connection '{connection}' is kind='{profile.kind}', not a database."
            )
        return profile

    @mcp.tool
    @redacted
    async def db_query(connection: str, sql: str, params: dict | None = None) -> dict:
        """Run a read-only query on a database connection.

        The statement always runs inside a transaction that is rolled back, so an
        accidental write has no effect. Use named params (``:name``) in ``sql`` with
        matching keys in ``params``. For Redis connections, pass a single command in
        ``sql`` (e.g. ``"GET mykey"``); ``params`` is ignored.
        """
        profile = _require_db(connection)
        connector = await registry.get(connection)
        if profile.kind == "redis":
            value = await connector.redis_command(*sql.split())
            registry.audit.record(
                connection=connection, operation="db_query", status="ok", detail=sql[:200]
            )
            return {"value": value}
        columns, rows = await connector.query(sql, params)
        registry.audit.record(
            connection=connection, operation="db_query", status="ok", detail=sql[:200]
        )
        return {"columns": columns, "rows": rows, "row_count": len(rows)}

    @mcp.tool
    @redacted
    async def db_execute(connection: str, sql: str, params: dict | None = None) -> dict:
        """Run a write statement (INSERT/UPDATE/DELETE/DDL) and commit.

        Blocked when the connection (or server) is in read-only mode. Not supported
        for Redis. Uses the same named-param convention as db_query.
        """
        profile = _require_db(connection)
        if profile.kind == "redis":
            raise ServerOpsError("db_execute is not supported for Redis; use db_query with a command.")
        if profile.kind == "clickhouse":
            raise ServerOpsError(
                "db_execute is not supported for ClickHouse; only read queries via db_query."
            )
        registry.safety.check_write(profile.read_only, "db_execute")
        connector = await registry.get(connection)
        result = await connector.execute(sql, params)
        registry.audit.record(
            connection=connection, operation="db_execute", status="ok", detail=sql[:200]
        )
        return result

    @mcp.tool
    @redacted
    async def db_tables(connection: str) -> dict:
        """List tables in a SQL database. Not supported for Redis."""
        profile = _require_db(connection)
        if profile.kind == "redis":
            raise ServerOpsError("db_tables is not supported for Redis.")
        connector = await registry.get(connection)
        return {"tables": await connector.tables()}

    @mcp.tool
    @redacted
    async def db_schema(connection: str, table: str) -> dict:
        """Describe the columns of a SQL table. Not supported for Redis."""
        profile = _require_db(connection)
        if profile.kind == "redis":
            raise ServerOpsError("db_schema is not supported for Redis.")
        connector = await registry.get(connection)
        return {"table": table, "columns": await connector.schema(table)}
