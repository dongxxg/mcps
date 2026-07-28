"""FastMCP application factory + module-level app for `fastmcp dev`."""

from __future__ import annotations

from fastmcp import FastMCP

from .config import ConfigError, load_config
from .models import ServerOpsConfig
from .registry import ConnectorRegistry
from .tools import container_tools, db_tools, meta, ssh_tools


def create_app(registry: ConnectorRegistry, auth=None) -> FastMCP:
    """Build a FastMCP app with all tool groups registered against ``registry``.

    ``auth`` is an optional FastMCP auth provider (e.g. ``StaticTokenVerifier``),
    applied at construction time. Only meaningful for the HTTP transport.
    """
    mcp = FastMCP(name="serverOps", auth=auth)
    meta.register(mcp, registry)
    ssh_tools.register(mcp, registry)
    db_tools.register(mcp, registry)
    container_tools.register(mcp, registry)
    return mcp


def bootstrap_registry(explicit: str | None = None) -> ConnectorRegistry:
    """Load config strictly; bad/missing config fails fast (used by the entrypoint)."""
    return ConnectorRegistry(load_config(explicit))


def _bootstrap_or_empty() -> ConnectorRegistry:
    """Tolerate a missing config so `fastmcp dev server.py` still loads (0 connections)."""
    try:
        return bootstrap_registry()
    except ConfigError:
        return ConnectorRegistry(ServerOpsConfig())


def add_health_route(mcp: FastMCP) -> None:
    """Mount GET /health (HTTP transport). No-op if Starlette isn't importable."""
    try:
        from starlette.requests import Request
        from starlette.responses import JSONResponse
    except ImportError:  # pragma: no cover - starlette ships with fastmcp
        return

    @mcp.custom_route("/health", methods=["GET"])
    async def _health(request: Request) -> JSONResponse:  # noqa: ARG001
        return JSONResponse({"status": "ok"})


# Module-level app so `fastmcp dev src/serverops/server.py` (which looks for an
# object named mcp/server/app) can find it.
mcp: FastMCP = create_app(_bootstrap_or_empty())
