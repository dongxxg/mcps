"""Database connector: SQL databases via SQLAlchemy async, Redis via redis.asyncio,
ClickHouse via clickhouse-connect.

Heavy libraries are imported lazily so the package imports cleanly even when the
'db' extra is not installed. SQL queries run on a connection that is rolled back,
so ``query`` is physically read-only; ``execute`` is the (gated) write path.

ClickHouse has no transaction/rollback support, so the rollback trick does not
apply. Instead its ``query`` is guarded by a leading-keyword allowlist (only
SELECT/SHOW/DESCRIBE-style statements pass) and ``execute`` is refused outright
— ClickHouse is query-only by design.
"""

from __future__ import annotations

import datetime
import decimal
import re
import urllib.parse
import uuid
from typing import Any

import anyio

from ..connectors.base import AsyncConnector, HealthStatus
from ..errors import ConnectionFailed, MissingDependency, ServerOpsError

_DB_HINT = "Database support requires the 'db' extra: pip install 'serverops[db]'"
_REDIS_HINT = "Redis support requires the 'db' extra: pip install 'serverops[db]'"
_CH_HINT = "ClickHouse support requires the 'db' extra: pip install 'serverops[db]'"

#: Leading keywords of ClickHouse statements that return data without mutating
#: state. Everything else (INSERT/CREATE/DROP/ALTER/TRUNCATE/...) is rejected.
_CLICKHOUSE_READ_LEAD: frozenset[str] = frozenset(
    {"SELECT", "WITH", "SHOW", "DESCRIBE", "DESC", "EXPLAIN", "EXISTS"}
)

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT = re.compile(r"--[^\n]*")
_FIRST_TOKEN = re.compile(r"[A-Za-z]+")
#: ``:name`` (serverOps-wide convention) -> ``%(name)s`` (clickhouse-connect style).
#: The lookbehind leaves ClickHouse ``::Type`` casts untouched.
_CH_PARAM = re.compile(r"(?<!:):([A-Za-z_][A-Za-z0-9_]*)")

#: Schemes that select HTTPS transport for ClickHouse.
_CH_SECURE_SCHEMES: frozenset[str] = frozenset(
    {"clickhouse+https", "clickhouses", "clickhouse+secure"}
)


def _json_safe(value: Any) -> Any:
    """Coerce a DB cell value into something JSON-serializable."""
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray)):
        try:
            return bytes(value).decode("utf-8")
        except UnicodeDecodeError:
            return bytes(value).hex()
    return value


def _require_clickhouse_read(sql: str) -> None:
    """Reject any ClickHouse statement that is not a read query.

    ClickHouse has no transaction/rollback, so this leading-keyword allowlist is
    the actual guarantee that ``db_query`` cannot mutate state (it complements
    the hard block on ``db_execute``).
    """
    stripped = _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub("", sql))
    # tolerate leading whitespace / ';' / '('  (e.g. "(SELECT ...)")
    while stripped[:1] in (" ", "\t", "\n", "\r", ";", "("):
        stripped = stripped[1:]
    match = _FIRST_TOKEN.match(stripped)
    keyword = match.group(0).upper() if match else ""
    if keyword not in _CLICKHOUSE_READ_LEAD:
        raise ServerOpsError(
            "ClickHouse db_query is read-only; only SELECT/SHOW/DESCRIBE-style "
            f"statements are allowed (leading keyword: {keyword or '(empty)'}). "
            "Use db_execute? It is disabled for ClickHouse by design."
        )


def _ch_bind_params(sql: str, params: dict | None) -> tuple[str, dict | None]:
    """Translate ``:name`` placeholders to clickhouse-connect ``%(name)s`` style.

    Returns ``(sql, parameters)``; ``parameters`` is ``None`` when no params were
    supplied, so the driver skips ``%``-formatting entirely (a literal ``%`` in
    a parameterless query is then safe). Note: when params ARE supplied, any
    literal ``%`` in the SQL must be escaped as ``%%`` (Python %-formatting).
    """
    if not params:
        return sql, None
    return _CH_PARAM.sub(r"%(\1)s", sql), dict(params)


def _ch_params_from_url(url: str) -> dict[str, Any]:
    """Map a ``clickhouse://`` URL to ``clickhouse_connect.get_client`` kwargs.

    Schemes: ``clickhouse`` / ``clickhouse+http`` -> HTTP (insecure, default port
    8123); ``clickhouse+https`` / ``clickhouses`` / ``clickhouse+secure`` -> HTTPS
    (secure, default port 8443). An explicit port in the URL always wins.
    """
    parsed = urllib.parse.urlparse(url)
    secure = parsed.scheme.lower() in _CH_SECURE_SCHEMES
    port = parsed.port if parsed.port is not None else (8443 if secure else 8123)
    database = parsed.path.lstrip("/") or None
    return {
        "host": parsed.hostname or "localhost",
        "port": port,
        "username": parsed.username or "default",
        "password": parsed.password or "",
        "database": database,
        "secure": secure,
    }


class DatabaseConnector(AsyncConnector):
    kind = "database"

    def __init__(self, name: str, profile: Any) -> None:
        super().__init__(name, profile)
        self._engine: Any = None
        self._redis: Any = None
        self._ch: Any = None  # clickhouse-connect client

    def is_redis(self) -> bool:
        return self.profile.kind == "redis"

    def is_clickhouse(self) -> bool:
        return self.profile.kind == "clickhouse"

    # -- connection ------------------------------------------------------

    def _sqlalchemy_url(self) -> str:
        kind = self.profile.kind
        url = self.profile.url
        if kind == "postgres":
            for prefix in ("postgresql+asyncpg://",):
                if url.startswith(prefix):
                    return url
            for prefix in ("postgres://", "postgresql://"):
                if url.startswith(prefix):
                    return "postgresql+asyncpg://" + url[len(prefix):]
        if kind == "mysql":
            if url.startswith("mysql+aiomysql://"):
                return url
            if url.startswith("mysql://"):
                return "mysql+aiomysql://" + url[len("mysql://"):]
        if kind == "sqlite":
            if url.startswith("sqlite+aiosqlite://"):
                return url
            if url.startswith("sqlite://"):
                return "sqlite+aiosqlite://" + url[len("sqlite://"):]
            return "sqlite+aiosqlite:///" + url
        return url

    async def connect(self) -> None:
        if self.is_redis():
            try:
                import redis.asyncio as redis_asyncio  # type: ignore[import-not-found]
            except ImportError as e:  # optional extra not installed
                raise MissingDependency(_REDIS_HINT) from e
            try:
                self._redis = redis_asyncio.from_url(self.profile.url, decode_responses=True)
            except Exception as e:  # noqa: BLE001 - surface as ConnectionFailed
                raise ConnectionFailed(f"Redis connect failed: {e}") from e
        elif self.is_clickhouse():
            try:
                import clickhouse_connect  # type: ignore[import-not-found]
            except ImportError as e:  # optional extra not installed
                raise MissingDependency(_CH_HINT) from e
            try:
                self._ch = clickhouse_connect.get_client(**_ch_params_from_url(self.profile.url))
            except Exception as e:  # noqa: BLE001 - surface as ConnectionFailed
                raise ConnectionFailed(f"ClickHouse connect failed: {e}") from e
        else:
            try:
                from sqlalchemy.ext.asyncio import (
                    create_async_engine,  # type: ignore[import-not-found]
                )
            except ImportError as e:  # optional extra not installed
                raise MissingDependency(_DB_HINT) from e
            try:
                self._engine = create_async_engine(self._sqlalchemy_url())
            except Exception as e:  # noqa: BLE001
                raise ConnectionFailed(f"DB engine creation failed: {e}") from e

    async def health(self) -> HealthStatus:
        try:
            if self.is_redis():
                await self._redis.ping()
            elif self.is_clickhouse():
                await anyio.to_thread.run_sync(self._ch.query, "SELECT 1")
            else:
                from sqlalchemy import text

                async with self._engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))
            return HealthStatus(healthy=True)
        except Exception as e:  # noqa: BLE001 - probe must not raise
            return HealthStatus(healthy=False, detail=str(e))

    # -- SQL operations --------------------------------------------------

    async def query(self, sql: str, params: dict | None = None) -> tuple[list[str], list[list[Any]]]:
        """Run a statement read-only and return ``(columns, rows)``.

        SQLAlchemy backends execute then ROLLBACK (physically read-only).
        ClickHouse is guarded by ``_require_clickhouse_read`` instead (no
        transaction support), so only SELECT-style statements are accepted.
        """
        if self.is_clickhouse():
            _require_clickhouse_read(sql)
            ch_sql, parameters = _ch_bind_params(sql, params)
            result = await anyio.to_thread.run_sync(self._ch.query, ch_sql, parameters)
            columns = list(result.column_names)
            rows = [[_json_safe(v) for v in row] for row in result.result_rows]
            return columns, rows

        from sqlalchemy import text

        async with self._engine.connect() as conn:
            result = await conn.execute(text(sql), params or {})
            returns_rows = getattr(result, "returns_rows", False)
            columns = list(result.keys()) if returns_rows else []
            rows = (
                [[_json_safe(v) for v in row] for row in result.fetchall()]
                if returns_rows
                else []
            )
            await conn.rollback()  # discard any writes -> query is physically read-only
        return columns, rows

    async def execute(self, sql: str, params: dict | None = None) -> dict[str, Any]:
        if self.is_clickhouse():
            raise ServerOpsError(
                "db_execute is not supported for ClickHouse; only read queries via db_query."
            )

        from sqlalchemy import text

        async with self._engine.begin() as conn:  # commits on success
            result = await conn.execute(text(sql), params or {})
            rowcount = result.rowcount
        return {"rowcount": rowcount}

    async def tables(self) -> list[str]:
        if self.is_clickhouse():
            result = await anyio.to_thread.run_sync(self._ch.query, "SHOW TABLES")
            return [row[0] for row in result.result_rows]

        from sqlalchemy import inspect

        async with self._engine.connect() as conn:
            names = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())
        return names

    async def schema(self, table: str) -> list[dict[str, Any]]:
        if self.is_clickhouse():
            # DESCRIBE TABLE returns rows like
            # (name, type, default_type, default_expression, comment, ...).
            result = await anyio.to_thread.run_sync(
                self._ch.query, f"DESCRIBE TABLE {table}"
            )
            idx = {name: i for i, name in enumerate(result.column_names)
                   if name in {"name", "type", "default_expression"}}
            columns: list[dict[str, Any]] = []
            for row in result.result_rows:
                col_type = str(row[idx["type"]])
                default = None
                if "default_expression" in idx:
                    expr = row[idx["default_expression"]]
                    default = expr if isinstance(expr, str) and expr else None
                columns.append(
                    {
                        "name": str(row[idx["name"]]),
                        "type": col_type,
                        "nullable": "Nullable" in col_type,
                        "default": default,
                    }
                )
            return columns

        from sqlalchemy import inspect

        def _columns(sync_conn) -> list[dict[str, Any]]:
            return [
                {
                    "name": c["name"],
                    "type": str(c["type"]),
                    "nullable": c.get("nullable"),
                    "default": c.get("default"),
                }
                for c in inspect(sync_conn).get_columns(table)
            ]

        async with self._engine.connect() as conn:
            return await conn.run_sync(_columns)

    # -- Redis operations ------------------------------------------------

    async def redis_command(self, *args: Any) -> Any:
        return _json_safe(await self._redis.execute_command(*args))

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None
        if self._ch is not None:
            # clickhouse-connect close() is synchronous
            self._ch.close()
            self._ch = None


def build(name: str, profile: Any) -> DatabaseConnector:
    return DatabaseConnector(name, profile)
