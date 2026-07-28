"""Container tools: Docker (ps/logs/exec/stats) and Kubernetes (pods/logs/describe/exec)."""

from __future__ import annotations

import shlex

from ..errors import ServerOpsError
from ._common import redacted


def register(mcp, registry) -> None:
    def _require(connection: str, kind: str):
        profile = registry.get_profile(connection)
        if profile.kind != kind:
            raise ServerOpsError(
                f"Connection '{connection}' is kind='{profile.kind}', not '{kind}'."
            )
        return profile

    # ----- Docker -------------------------------------------------------

    @mcp.tool
    @redacted
    async def docker_ps(connection: str, all: bool = True) -> dict:
        """List containers on a Docker host. Set all=False for running-only."""
        _require(connection, "docker")
        connector = await registry.get(connection)
        return {"containers": await connector.ps(all_containers=all)}

    @mcp.tool
    @redacted
    async def docker_logs(connection: str, container: str, tail: int = 200) -> dict:
        """Fetch the combined stdout/stderr logs of a container."""
        _require(connection, "docker")
        connector = await registry.get(connection)
        return {"logs": await connector.logs(container, tail=tail)}

    @mcp.tool
    @redacted
    async def docker_exec(connection: str, container: str, command: str) -> dict:
        """Run a command inside a running container (subject to read-only gating).

        ``command`` is a single string, shell-split into argv (e.g. ``"ls -la /app"``).
        """
        _require(connection, "docker")
        registry.safety.check_write(registry.get_profile(connection).read_only, "docker_exec")
        connector = await registry.get(connection)
        result = await connector.exec(container, shlex.split(command))
        registry.audit.record(
            connection=connection,
            operation="docker_exec",
            status="ok",
            detail=f"{container}: {command[:200]}",
        )
        return result

    @mcp.tool
    @redacted
    async def docker_stats(connection: str, container: str) -> dict:
        """Return a one-sample resource snapshot (memory/cpu) for a container."""
        _require(connection, "docker")
        connector = await registry.get(connection)
        return await connector.stats(container)

    # ----- Kubernetes ---------------------------------------------------

    @mcp.tool
    @redacted
    async def k8s_list_pods(connection: str, namespace: str | None = None) -> dict:
        """List pods in a namespace (defaults to the connection's namespace)."""
        _require(connection, "kubernetes")
        connector = await registry.get(connection)
        return {"pods": await connector.list_pods(namespace)}

    @mcp.tool
    @redacted
    async def k8s_pod_logs(connection: str, name: str, namespace: str | None = None, tail: int = 200) -> dict:
        """Fetch the logs of a pod."""
        _require(connection, "kubernetes")
        connector = await registry.get(connection)
        return {"logs": await connector.pod_logs(name, namespace, tail=tail)}

    @mcp.tool
    @redacted
    async def k8s_describe(connection: str, name: str, namespace: str | None = None) -> dict:
        """Describe a pod (key fields, no raw secret/configmap data)."""
        _require(connection, "kubernetes")
        connector = await registry.get(connection)
        return {"pod": await connector.describe(name, namespace)}

    @mcp.tool
    @redacted
    async def k8s_exec(connection: str, name: str, command: str, namespace: str | None = None) -> dict:
        """Run a command in a pod's first container (subject to read-only gating).

        ``command`` is a single string, shell-split into argv.
        """
        _require(connection, "kubernetes")
        registry.safety.check_write(registry.get_profile(connection).read_only, "k8s_exec")
        connector = await registry.get(connection)
        result = await connector.exec(name, shlex.split(command), namespace)
        registry.audit.record(
            connection=connection,
            operation="k8s_exec",
            status="ok",
            detail=f"{name}: {command[:200]}",
        )
        return result
