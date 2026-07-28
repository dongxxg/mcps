"""Elasticsearch connector: read-only queries via elasticsearch-py async client.

Only three operations are exposed — ``search``, ``get``, and ``indices`` — so the
connector is query-only by construction. ``execute``/``write``/``delete`` are
never provided, eliminating any accidental-mutation path.

Heavy libraries are imported lazily so the package imports cleanly even when the
'elasticsearch' extra is not installed.
"""

from __future__ import annotations

import json
from typing import Any

from ..connectors.base import AsyncConnector, HealthStatus
from ..errors import ConnectionFailed, MissingDependency, ServerOpsError

_ES_HINT = "Elasticsearch support requires the 'elasticsearch' extra: pip install 'serverops[elasticsearch]'"

#: Hard ceiling on ``size`` passed to the ES _search API. Prevents accidental or
#: malicious deep-pagination / heap exhaustion on the cluster.
_MAX_SEARCH_SIZE: int = 200

#: Default page size when the caller does not specify one.
_DEFAULT_SEARCH_SIZE: int = 10

#: Elasticsearch default `index.max_result_window`; we refuse to go beyond it
#: via the ``from`` parameter because that triggers an expensive deep-skip.
_MAX_FROM: int = 10_000


class ElasticsearchConnector(AsyncConnector):
    kind = "elasticsearch"

    def __init__(self, name: str, profile: Any) -> None:
        super().__init__(name, profile)
        self._client: Any = None

    # -- connection ------------------------------------------------------

    async def connect(self) -> None:
        try:
            from elasticsearch import AsyncElasticsearch  # type: ignore[import-not-found]
        except ImportError as e:
            raise MissingDependency(_ES_HINT) from e
        try:
            self._client = AsyncElasticsearch.from_url(str(self.profile.url))
        except Exception as e:  # noqa: BLE001
            raise ConnectionFailed(f"Elasticsearch connect failed: {e}") from e

    async def health(self) -> HealthStatus:
        if self._client is None:
            return HealthStatus(healthy=False, detail="not connected")
        try:
            info = await self._client.info()
            return HealthStatus(healthy=True, detail=f"cluster={info.get('cluster_name', '?')}")
        except Exception as e:  # noqa: BLE001
            return HealthStatus(healthy=False, detail=str(e))

    # -- query operations ------------------------------------------------

    async def search(
        self,
        index: str,
        body: dict[str, Any],
        *,
        size: int | None = None,
        from_: int = 0,
    ) -> dict[str, Any]:
        """Execute a search query.

        ``size`` is clamped to ``[_DEFAULT_SEARCH_SIZE, _MAX_SEARCH_SIZE]``.
        ``from_`` is rejected above ``_MAX_FROM``.
        Any ``body`` containing a top-level ``script`` key is rejected because
        it would allow arbitrary Painless script execution.
        """
        # Reject scripted queries — they execute server-side code (Painless).
        if "script" in body:
            raise ServerOpsError(
                "Elasticsearch search with 'script' is not permitted. "
                "Remove the 'script' key from the query body."
            )

        # Reject nested script constructs inside `query` and `aggs`
        body_str = json.dumps(body)
        if '"script"' in body_str:
            raise ServerOpsError(
                "Elasticsearch search containing 'script' is not permitted. "
                "Remove any script_score / scripted_metric / script filters."
            )

        effective_size = _DEFAULT_SEARCH_SIZE if size is None else size
        if effective_size > _MAX_SEARCH_SIZE:
            raise ServerOpsError(
                f"es_search size {effective_size} exceeds the maximum of {_MAX_SEARCH_SIZE}."
            )
        if from_ > _MAX_FROM:
            raise ServerOpsError(
                f"es_search from {from_} exceeds the maximum of {_MAX_FROM}."
            )

        # Pass through to ES (the elasticsearch-py methods are async I/O).
        result = await self._client.search(
            index=index,
            body=body,
            size=effective_size,
            from_=from_,
        )
        # Strip heavy metadata that agents rarely need.
        result.pop("profile", None)
        result.pop("pit", None)
        return result

    async def get(self, index: str, doc_id: str) -> dict[str, Any]:
        """Retrieve a single document by ID."""
        return await self._client.get(index=index, id=doc_id)

    async def indices(self) -> dict[str, Any]:
        """Return a map of index-name → alias/template metadata."""
        return await self._client.indices.get_alias(index="*")

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None


def build(name: str, profile: Any) -> ElasticsearchConnector:
    return ElasticsearchConnector(name, profile)
