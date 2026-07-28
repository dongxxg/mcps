"""Docker connector (aiodocker). The library is imported lazily at connect time."""

from __future__ import annotations

import contextlib
from typing import Any

from ..connectors.base import AsyncConnector, HealthStatus
from ..errors import ConnectionFailed, MissingDependency

_HINT = "Docker support requires the 'container' extra: pip install 'serverops[container]'"


def _opt(container: Any, key: str) -> Any:
    """Read a field from a container object (dict or aiodocker DockerContainer)."""
    try:
        return container[key]
    except (KeyError, TypeError, IndexError):
        return None


class DockerConnector(AsyncConnector):
    kind = "docker"

    def __init__(self, name: str, profile: Any) -> None:
        super().__init__(name, profile)
        self._docker: Any = None

    async def connect(self) -> None:
        try:
            import aiodocker  # type: ignore[import-not-found]
        except ImportError as e:  # optional extra not installed
            raise MissingDependency(_HINT) from e
        try:
            self._docker = aiodocker.Docker(url=self.profile.url)
        except Exception as e:  # noqa: BLE001
            raise ConnectionFailed(f"Docker client init failed: {e}") from e

    async def health(self) -> HealthStatus:
        if self._docker is None:
            return HealthStatus(healthy=False, detail="not connected")
        try:
            await self._docker.version()
            return HealthStatus(healthy=True)
        except Exception as e:  # noqa: BLE001 - probe must not raise
            return HealthStatus(healthy=False, detail=str(e))

    async def ps(self, all_containers: bool = True) -> list[dict[str, Any]]:
        containers = await self._docker.containers.list(all=all_containers)
        rows: list[dict[str, Any]] = []
        for c in containers:
            names = _opt(c, "Names") or []
            first = names[0].lstrip("/") if names else None
            rows.append(
                {
                    "id": _opt(c, "Id"),
                    "name": first,
                    "image": _opt(c, "Image"),
                    "state": _opt(c, "State"),
                    "status": _opt(c, "Status"),
                }
            )
        return rows

    async def logs(self, container: str, tail: int = 200) -> str:
        handle = self._docker.containers.container(container)
        lines = await handle.log(stdout=True, stderr=True, tail=tail)
        return "".join(lines)

    async def exec(self, container: str, command: list[str]) -> dict[str, Any]:
        handle = self._docker.containers.container(container)
        exec_obj = await handle.exec(cmd=command)
        stream = await exec_obj.start()
        chunks: list[str] = []
        async for chunk in stream:
            chunks.append(chunk if isinstance(chunk, str) else chunk.decode("utf-8", "replace"))
        info = await exec_obj.inspect()
        return {"exit_code": _opt(info, "ExitCode"), "output": "".join(chunks)}

    async def stats(self, container: str) -> dict[str, Any]:
        handle = self._docker.containers.container(container)
        info = await handle.show()
        sample = await handle.stats(stream=False)
        mem = sample.get("memory_stats", {}) if isinstance(sample, dict) else {}
        cpu = sample.get("cpu_stats", {}) if isinstance(sample, dict) else {}
        usage = mem.get("usage")
        limit = mem.get("limit")
        return {
            "name": _opt(info, "Name"),
            "state": _opt(_opt(info, "State"), "Status"),
            "memory_usage_mb": round(usage / 1024 / 1024, 2) if usage else None,
            "memory_limit_mb": round(limit / 1024 / 1024, 2) if limit else None,
            "cpu_count": cpu.get("online_cpus"),
        }

    async def close(self) -> None:
        if self._docker is not None:
            with contextlib.suppress(Exception):
                await self._docker.close()
            self._docker = None


def build(name: str, profile: Any) -> DockerConnector:
    return DockerConnector(name, profile)
