"""Meta tools: introspection of configured connections and server health."""

from __future__ import annotations

from ..redaction import redact
from ._common import redacted


def register(mcp, registry) -> None:
    @mcp.tool
    @redacted
    async def connection_list() -> dict:
        """List every configured remote-service connection.

        Returns each connection's name, kind, whether it is effectively read-only,
        and its optional description. No credentials.
        """
        conns = [
            {
                "name": name,
                "kind": profile.kind,
                "read_only": registry.safety.effective_read_only(profile.read_only),
                "description": profile.description,
            }
            for name, profile in registry.config.connections.items()
        ]
        return {"connections": conns, "count": len(conns)}

    @mcp.tool
    @redacted
    async def connection_ping(connection: str) -> dict:
        """Probe a named connection and report whether it is reachable/healthy."""
        connector = await registry.get(connection)
        status = await connector.health()
        return {
            "connection": connection,
            "healthy": status.healthy,
            "detail": status.detail,
        }

    @mcp.tool
    @redacted
    async def connection_info(connection: str) -> dict:
        """Show non-sensitive details for a connection (credentials are redacted)."""
        profile = registry.get_profile(connection)
        data = profile.model_dump()
        if data.get("url"):
            data["url"] = redact(data["url"])
        data.pop("password_env", None)
        data["read_only"] = registry.safety.effective_read_only(profile.read_only)
        return data

    @mcp.tool
    @redacted
    async def server_health() -> dict:
        """Ping every configured connection and return an aggregate health summary."""
        results = []
        for name in registry.connection_names():
            try:
                connector = await registry.get(name)
                status = await connector.health()
                results.append(
                    {"name": name, "healthy": status.healthy, "detail": status.detail}
                )
            except Exception as e:  # noqa: BLE001 - one bad connection shouldn't hide others
                results.append({"name": name, "healthy": False, "detail": str(e)})
        healthy = sum(1 for r in results if r["healthy"])
        return {"healthy": healthy, "total": len(results), "connections": results}
