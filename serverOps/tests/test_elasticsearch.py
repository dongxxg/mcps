"""Elasticsearch connector + tools.

No real ES cluster is required: ``elasticsearch`` is replaced in ``sys.modules``
with a fake that records the connect kwargs, search calls, and get calls. The
real driver is never imported.

Core guarantee under test: ES is **query-only by construction** — only
``search``, ``get``, and ``indices`` operations exist; ``execute``/write paths
are never exposed. ``es_search`` additionally enforces size/from caps and
rejects query bodies containing ``script``.
"""

from __future__ import annotations

import json
import sys
import types
from typing import Any

import pytest

from serverops.connectors.elasticsearch import (
    _MAX_FROM,
    _MAX_SEARCH_SIZE,
    ElasticsearchConnector,
)
from serverops.errors import ServerOpsError
from serverops.models import ElasticsearchProfile, ServerOpsConfig
from serverops.registry import ConnectorRegistry
from serverops.tools import es_tools

# ---------------------------------------------------------------------------
# Fake elasticsearch-py driver
# ---------------------------------------------------------------------------


class _FakeIndices:
    def __init__(self) -> None:
        self._parent: _FakeESClient | None = None

    def set_parent(self, parent: _FakeESClient) -> None:
        self._parent = parent

    async def get_alias(self, **kwargs: Any) -> dict[str, Any]:
        assert self._parent is not None
        self._parent.indices_calls += 1
        return {"test-index": {"aliases": {}}}


class _FakeESClient:
    def __init__(self) -> None:
        self.connect_kwargs: dict[str, Any] | None = None
        self.searches: list[dict[str, Any]] = []
        self.gets: list[tuple[str, str]] = []
        self.indices_calls: int = 0
        self.closed = False
        self.indices = _FakeIndices()
        self.indices.set_parent(self)

        self._health_info: dict[str, Any] = {"cluster_name": "test-cluster"}

    # -- health helper ---------------------------------------------------
    def set_health(self, healthy: bool = True, **info: Any) -> None:
        self._health_info = {"cluster_name": info.get("cluster_name", "test-cluster")}

    # -- AsyncElasticsearch interface ------------------------------------
    async def info(self) -> dict[str, Any]:
        return self._health_info

    async def search(
        self, index: str, body: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        self.searches.append({"index": index, "body": body, **kwargs})
        return {"hits": {"total": {"value": 0}, "hits": []}, **kwargs}

    async def get(self, index: str, id: str, **kwargs: Any) -> dict[str, Any]:
        self.gets.append((index, id))
        return {"_index": index, "_id": id, "_source": {"id": id}, **kwargs}

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_es(monkeypatch: pytest.MonkeyPatch) -> _FakeESClient:
    """Inject a fake ``elasticsearch`` module so ``connect()`` never hits the network."""
    client = _FakeESClient()
    mod = types.ModuleType("elasticsearch")

    class _FakeAsyncES:
        @staticmethod
        def from_url(url: str, **kwargs: Any) -> _FakeESClient:
            client.connect_kwargs = {"url": url, **kwargs}
            return client

    mod.AsyncElasticsearch = _FakeAsyncES
    monkeypatch.setitem(sys.modules, "elasticsearch", mod)
    return client


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


async def _es_conn(url: str = "http://localhost:9200") -> ElasticsearchConnector:
    conn = ElasticsearchConnector("es", ElasticsearchProfile(url=url))
    await conn.connect()
    return conn


def _es_registry(url: str = "http://localhost:9200") -> ConnectorRegistry:
    cfg = ServerOpsConfig.model_validate(
        {"connections": {"es": {"kind": "elasticsearch", "url": url}}}
    )
    reg = ConnectorRegistry(cfg)
    from serverops.connectors import elasticsearch as es_module

    reg._build = lambda name, profile: es_module.build(name, profile)  # type: ignore[method-assign]
    return reg


# ---------------------------------------------------------------------------
# Connector-level
# ---------------------------------------------------------------------------


async def test_connect_sets_client(fake_es: _FakeESClient) -> None:
    conn = await _es_conn("http://user:pass@es.host:9200")
    assert conn._client is fake_es
    assert fake_es.connect_kwargs["url"] == "http://user:pass@es.host:9200"
    await conn.close()


async def test_health_reports_cluster(fake_es: _FakeESClient) -> None:
    conn = await _es_conn()
    status = await conn.health()
    assert status.healthy is True
    assert "test-cluster" in status.detail
    await conn.close()


async def test_health_when_not_connected() -> None:
    conn = ElasticsearchConnector("es", ElasticsearchProfile(url="http://localhost:9200"))
    status = await conn.health()
    assert status.healthy is False
    assert "not connected" in status.detail


async def test_search_returns_result(fake_es: _FakeESClient) -> None:
    conn = await _es_conn()
    result = await conn.search("logs", {"query": {"match_all": {}}})
    assert "hits" in result
    assert fake_es.searches[-1]["index"] == "logs"
    assert fake_es.searches[-1]["size"] == 10  # default
    assert fake_es.searches[-1]["from_"] == 0
    await conn.close()


async def test_search_respects_size_and_from(fake_es: _FakeESClient) -> None:
    conn = await _es_conn()
    await conn.search("logs", {"query": {"match_all": {}}}, size=50, from_=10)
    call = fake_es.searches[-1]
    assert call["size"] == 50
    assert call["from_"] == 10
    await conn.close()


async def test_search_rejects_size_above_max(fake_es: _FakeESClient) -> None:
    conn = await _es_conn()
    with pytest.raises(ServerOpsError, match="exceeds the maximum"):
        await conn.search("logs", {"query": {"match_all": {}}}, size=_MAX_SEARCH_SIZE + 1)
    assert not fake_es.searches  # never reached ES
    await conn.close()


async def test_search_rejects_from_above_max(fake_es: _FakeESClient) -> None:
    conn = await _es_conn()
    with pytest.raises(ServerOpsError, match="from"):
        await conn.search("logs", {"query": {"match_all": {}}}, from_=_MAX_FROM + 1)
    assert not fake_es.searches  # never reached ES
    await conn.close()


async def test_search_rejects_script_key(fake_es: _FakeESClient) -> None:
    conn = await _es_conn()
    with pytest.raises(ServerOpsError, match="script"):
        await conn.search(
            "logs", {"query": {"script": {"source": "doc['field'].value > 1"}}}
        )
    assert not fake_es.searches
    await conn.close()


async def test_search_rejects_nested_script(fake_es: _FakeESClient) -> None:
    conn = await _es_conn()
    with pytest.raises(ServerOpsError, match="script"):
        await conn.search(
            "logs",
            {
                "aggs": {
                    "terms": {
                        "script": {"source": "doc['field'].value"}
                    }
                }
            },
        )
    assert not fake_es.searches
    await conn.close()


async def test_get_returns_doc(fake_es: _FakeESClient) -> None:
    conn = await _es_conn()
    result = await conn.get("logs", "doc-1")
    assert result["_id"] == "doc-1"
    assert fake_es.gets == [("logs", "doc-1")]
    await conn.close()


async def test_indices_returns_alias_map(fake_es: _FakeESClient) -> None:
    conn = await _es_conn()
    result = await conn.indices()
    assert "test-index" in result
    assert fake_es.indices_calls == 1
    await conn.close()


async def test_close_clears_client(fake_es: _FakeESClient) -> None:
    conn = await _es_conn()
    await conn.close()
    assert conn._client is None
    assert fake_es.closed is True


async def test_close_when_not_connected() -> None:
    conn = ElasticsearchConnector("es", ElasticsearchProfile(url="http://localhost:9200"))
    await conn.close()  # must not raise
    assert conn._client is None


# ---------------------------------------------------------------------------
# Connector-level: missing dependency
# ---------------------------------------------------------------------------


async def test_missing_elasticsearch_lib(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys as _sys

    # Ensure elasticsearch is NOT importable
    monkeypatch.delitem(_sys.modules, "elasticsearch", raising=False)
    # Block any real import
    import importlib

    _orig = importlib.__import__

    def _block_es(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "elasticsearch" or name.startswith("elasticsearch."):
            raise ImportError("no module named 'elasticsearch'")
        return _orig(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "__import__", _block_es)
    # Clear any cached module
    for key in list(_sys.modules):
        if key == "elasticsearch" or key.startswith("elasticsearch."):
            del _sys.modules[key]

    from serverops.errors import MissingDependency

    conn = ElasticsearchConnector(
        "es", ElasticsearchProfile(url="http://localhost:9200")
    )
    with pytest.raises(MissingDependency, match="elasticsearch"):
        await conn.connect()


# ---------------------------------------------------------------------------
# Tool-level
# ---------------------------------------------------------------------------


async def test_tool_search(fake_es: _FakeESClient, fake_mcp) -> None:
    reg = _es_registry()
    es_tools.register(fake_mcp, reg)
    result = await fake_mcp.tools["es_search"](
        "es", "logs", {"query": {"match_all": {}}}
    )
    assert "hits" in result
    assert fake_es.searches[-1]["index"] == "logs"


async def test_tool_get(fake_es: _FakeESClient, fake_mcp) -> None:
    reg = _es_registry()
    es_tools.register(fake_mcp, reg)
    result = await fake_mcp.tools["es_get"]("es", "logs", "doc-1")
    assert result["_id"] == "doc-1"
    assert fake_es.gets == [("logs", "doc-1")]


async def test_tool_indices(fake_es: _FakeESClient, fake_mcp) -> None:
    reg = _es_registry()
    es_tools.register(fake_mcp, reg)
    result = await fake_mcp.tools["es_indices"]("es")
    assert "test-index" in result


async def test_tool_search_rejects_script(fake_es: _FakeESClient, fake_mcp) -> None:
    reg = _es_registry()
    es_tools.register(fake_mcp, reg)
    with pytest.raises(ServerOpsError, match="script"):
        await fake_mcp.tools["es_search"](
            "es",
            "logs",
            {"query": {"script": {"source": "1"}}},
        )


async def test_tool_rejects_non_es_connection(fake_mcp) -> None:
    cfg = ServerOpsConfig.model_validate(
        {"connections": {"web1": {"kind": "ssh", "host": "h", "user": "u"}}}
    )
    reg = ConnectorRegistry(cfg)
    es_tools.register(fake_mcp, reg)
    with pytest.raises(ServerOpsError):
        await fake_mcp.tools["es_search"]("web1", "logs", {"query": {"match_all": {}}})


async def test_tool_audit_recorded(fake_es: _FakeESClient, fake_mcp, tmp_path) -> None:
    audit_path = str(tmp_path / "audit.jsonl")
    cfg = ServerOpsConfig.model_validate(
        {
            "settings": {"audit_log": audit_path},
            "connections": {"es": {"kind": "elasticsearch", "url": "http://localhost:9200"}},
        }
    )
    reg = ConnectorRegistry(cfg)
    from serverops.connectors import elasticsearch as es_module

    reg._build = lambda name, profile: es_module.build(name, profile)  # type: ignore[method-assign]
    es_tools.register(fake_mcp, reg)
    await fake_mcp.tools["es_search"]("es", "logs", {"query": {"match_all": {}}})
    lines = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").strip().splitlines()
    entries = [json.loads(line) for line in lines]
    assert entries[-1]["operation"] == "es_search"
    assert entries[-1]["connection"] == "es"
    assert entries[-1]["status"] == "ok"


# ---------------------------------------------------------------------------
# Profile / model
# ---------------------------------------------------------------------------


def test_elasticsearch_profile_routes_through_union() -> None:
    cfg = ServerOpsConfig.model_validate(
        {"connections": {"es": {"kind": "elasticsearch", "url": "http://localhost:9200"}}}
    )
    assert isinstance(cfg.connections["es"], ElasticsearchProfile)
    assert cfg.connections["es"].kind == "elasticsearch"
