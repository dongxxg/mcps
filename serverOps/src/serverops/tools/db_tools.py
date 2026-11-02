"""Database tools: db_query (read-only) / db_execute (gated) / db_tables / db_schema.

Named parameters are used for SQL substitution (cross-driver safe):
``sql="SELECT * FROM users WHERE id = :id"``, ``params={"id": 1}``.
"""

from __future__ import annotations

import asyncio

from ..errors import ServerOpsError
from ..models import DATABASE_KINDS, QUERY_MAX_ROWS_CAP
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
    async def db_query(
        connection: str,
        sql: str,
        params: dict | None = None,
        max_rows: int | None = None,
        timeout_s: float | None = None,
    ) -> dict:
        """Run a read-only query on a database connection.

        The statement always runs inside a transaction that is rolled back, so an
        accidental write has no effect. Use named params (``:name``) in ``sql`` with
        matching keys in ``params``. For Redis connections, pass a single command in
        ``sql`` (e.g. ``"GET mykey"``); ``params`` is ignored — only read-only Redis
        commands (GET/SCAN/TTL/...) are allowed in read-only mode.

        Rows are capped: ``max_rows`` overrides the configured ``query_max_rows``
        (default 200, hard cap 2000). ``truncated`` reports whether more rows
        existed beyond the cap; raise ``max_rows`` or add a WHERE/LIMIT clause
        instead of pulling unbounded results into the conversation. A query that
        exceeds ``timeout_s`` (default 30s) is cancelled, audited, and its cached
        connection is dropped.
        """
        profile = _require_db(connection)
        if profile.kind == "elasticsearch":
            raise ServerOpsError(
                "db_query is not supported for Elasticsearch; use es_search / es_get / es_indices."
            )

        effective_max = registry.settings.query_max_rows if max_rows is None else max_rows
        if not 1 <= effective_max <= QUERY_MAX_ROWS_CAP:
            raise ServerOpsError(
                f"max_rows must be between 1 and {QUERY_MAX_ROWS_CAP} (got {effective_max})."
            )
        effective_timeout = (
            registry.settings.query_timeout_s if timeout_s is None else timeout_s
        )
        if effective_timeout <= 0:
            raise ServerOpsError(
                f"timeout_s must be positive (got {effective_timeout})."
            )

        async def _with_timeout(coro):
            try:
                return await asyncio.wait_for(coro, timeout=effective_timeout)
            except (asyncio.TimeoutError, TimeoutError):
                registry.audit.record(
                    connection=connection,
                    operation="db_query",
                    status="timeout",
                    detail=sql[:200],
                )
                await registry.invalidate(connection)  # connection may be stuck
                raise ServerOpsError(
                    f"db_query timed out after {effective_timeout}s; the cached "
                    "connection was dropped — retry to reconnect."
                ) from None

        if profile.kind == "redis":
            registry.safety.check_redis_command(profile.read_only, sql)
            connector = await registry.get(connection)
            value = await _with_timeout(connector.redis_command(*sql.split()))
            registry.audit.record(
                connection=connection, operation="db_query", status="ok", detail=sql[:200]
            )
            return {"value": value}

        connector = await registry.get(connection)
        columns, rows, truncated = await _with_timeout(
            connector.query(sql, params, limit=effective_max)
        )
        registry.audit.record(
            connection=connection, operation="db_query", status="ok", detail=sql[:200]
        )
        return {
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "truncated": truncated,
            "max_rows": effective_max,
        }

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
