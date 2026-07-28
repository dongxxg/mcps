"""Elasticsearch tools: es_search / es_get / es_indices.

Query-only by design: no write, delete, or index-creation operations are exposed.
``es_search`` enforces a maximum page size and rejects any query body that
contains ``script`` keys (Painless code execution is not permitted).
"""

from __future__ import annotations

from typing import Any

from ..errors import ServerOpsError
from ._common import redacted


def register(mcp, registry) -> None:
    def _require_es(connection: str):
        profile = registry.get_profile(connection)
        if profile.kind != "elasticsearch":
            raise ServerOpsError(
                f"Connection '{connection}' is kind='{profile.kind}', not 'elasticsearch'."
            )
        return profile

    @mcp.tool
    @redacted
    async def es_search(
        connection: str,
        index: str,
        query: dict[str, Any] | None = None,
        size: int | None = None,
        from_: int = 0,
    ) -> dict:
        """Execute a read-only search query on an Elasticsearch index.

        ``query`` is the Elasticsearch Query DSL body (a JSON object). A default
        ``match_all`` query is used when omitted.

        Security constraints:
        - ``size`` is capped at 200 (default: 10) to prevent heap exhaustion.
        - ``from_`` is rejected above 10 000.
        - Any body containing a ``script`` key (Painless) is refused.

        Named params use the same :name convention as db_query if needed in
        future extensions; today the query body is passed as a JSON object.
        """
        _require_es(connection)
        connector = await registry.get(connection)
        body = query if query is not None else {"query": {"match_all": {}}}
        result = await connector.search(index, body, size=size, from_=from_)
        registry.audit.record(
            connection=connection,
            operation="es_search",
            status="ok",
            detail=f"index={index}",
        )
        return result

    @mcp.tool
    @redacted
    async def es_get(connection: str, index: str, doc_id: str) -> dict:
        """Retrieve a single document from an Elasticsearch index by its ID."""
        _require_es(connection)
        connector = await registry.get(connection)
        result = await connector.get(index, doc_id)
        registry.audit.record(
            connection=connection,
            operation="es_get",
            status="ok",
            detail=f"index={index} id={doc_id}",
        )
        return result

    @mcp.tool
    @redacted
    async def es_indices(connection: str) -> dict:
        """List all Elasticsearch indices and their aliases."""
        _require_es(connection)
        connector = await registry.get(connection)
        result = await connector.indices()
        registry.audit.record(
            connection=connection,
            operation="es_indices",
            status="ok",
            detail="",
        )
        return result
