"""Registry + meta-tool behaviour (no real backends required)."""

from __future__ import annotations

import pytest

from serverops.connectors.base import AsyncConnector, HealthStatus
from serverops.errors import ServerOpsError, UnknownConnection
from serverops.models import ServerOpsConfig
from serverops.registry import ConnectorRegistry
from serverops.tools import meta
from serverops.tools._common import redacted


class FakeMCP:
    """Captures @mcp.tool-decorated callables into a dict for direct testing."""

    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self, fn=None, **_kwargs):
        if fn is not None and callable(fn):
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


class FakeConnector(AsyncConnector):
    kind = "ssh"

    async def connect(self) -> None:
        return None

    async def health(self) -> HealthStatus:
        return HealthStatus(True, "fake-ok")

    async def close(self) -> None:
        return None


def _registry_with_web1(read_only: bool = False) -> ConnectorRegistry:
    cfg = ServerOpsConfig.model_validate(
        {
            "connections": {
                "web1": {
                    "kind": "ssh",
                    "host": "h",
                    "user": "u",
                    "description": "frontend",
                    "read_only": read_only,
                }
            }
        }
    )
    reg = ConnectorRegistry(cfg)
    # avoid importing the real (optional) ssh backend
    reg._build = lambda name, profile: FakeConnector(name, profile)  # type: ignore[method-assign]
    return reg


async def test_connection_list_reports_kind_and_readonly() -> None:
    reg = _registry_with_web1(read_only=True)
    mcp = FakeMCP()
    meta.register(mcp, reg)

    result = await mcp.tools["connection_list"]()  # type: ignore[operator]
    assert result["count"] == 1
    entry = result["connections"][0]
    assert entry["name"] == "web1"
    assert entry["kind"] == "ssh"
    assert entry["read_only"] is True


async def test_connection_info_redacts_url_and_drops_password_env() -> None:
    cfg = ServerOpsConfig.model_validate(
        {"connections": {"db": {"kind": "postgres", "url": "postgresql://u:s3cret@h/db"}}}
    )
    reg = ConnectorRegistry(cfg)
    mcp = FakeMCP()
    meta.register(mcp, reg)

    info = await mcp.tools["connection_info"]("db")  # type: ignore[operator]
    assert info["url"] == "postgresql://u:***@h/db"
    assert "password_env" not in info


async def test_connection_ping_uses_connector() -> None:
    reg = _registry_with_web1()
    mcp = FakeMCP()
    meta.register(mcp, reg)
    result = await mcp.tools["connection_ping"]("web1")  # type: ignore[operator]
    assert result == {"connection": "web1", "healthy": True, "detail": "fake-ok"}


async def test_server_health_reports_per_connection() -> None:
    reg = _registry_with_web1()
    mcp = FakeMCP()
    meta.register(mcp, reg)
    result = await mcp.tools["server_health"]()  # type: ignore[operator]
    assert result["total"] == 1
    assert result["connections"][0]["healthy"] is True


async def test_unknown_connection_raises_cleanly() -> None:
    reg = _registry_with_web1()
    mcp = FakeMCP()
    meta.register(mcp, reg)
    with pytest.raises(UnknownConnection):
        await mcp.tools["connection_info"]("nope")  # type: ignore[operator]


async def test_redacted_wraps_unexpected_errors() -> None:
    @redacted
    async def boom() -> None:
        raise RuntimeError("postgres://alice:hunter2@host/db failed")

    with pytest.raises(ServerOpsError) as exc:
        await boom()
    assert "hunter2" not in str(exc.value)
    assert "***" in str(exc.value)


def test_create_app_builds_fastmcp() -> None:
    from fastmcp import FastMCP

    from serverops.server import create_app

    reg = ConnectorRegistry(ServerOpsConfig())
    app = create_app(reg)
    assert isinstance(app, FastMCP)


async def test_meta_tools_registered_on_real_fastmcp() -> None:
    from serverops.server import create_app

    app = create_app(_registry_with_web1())
    tools = await app.list_tools()
    names = {t.name for t in tools}
    assert {
        "connection_list",
        "connection_ping",
        "connection_info",
        "server_health",
    } <= names
