"""Connector registry: maps a connection name to a cached async connector."""

from __future__ import annotations

import contextlib
import importlib
from types import MappingProxyType
from typing import Any

from .audit import AuditLog
from .config import load_config
from .connectors.base import AsyncConnector
from .errors import MissingDependency, UnknownConnection
from .models import ServerOpsConfig
from .safety import SafetyPolicy

#: discriminator value -> connector module that implements ``build``.
_KIND_TO_MODULE: dict[str, str] = {
    "ssh": "serverops.connectors.ssh",
    "docker": "serverops.connectors.docker",
    "kubernetes": "serverops.connectors.kubernetes",
    "postgres": "serverops.connectors.database",
    "mysql": "serverops.connectors.database",
    "sqlite": "serverops.connectors.database",
    "redis": "serverops.connectors.database",
    "clickhouse": "serverops.connectors.database",
    "elasticsearch": "serverops.connectors.elasticsearch",
}

#: friendly install hint shown when an optional extra is missing.
_INSTALL_HINT: dict[str, str] = {
    "ssh": "pip install 'serverops[ssh]' (provides asyncssh)",
    "docker": "pip install 'serverops[container]' (provides aiodocker)",
    "kubernetes": "pip install 'serverops[k8s]' (provides kubernetes)",
    "postgres": "pip install 'serverops[db]' (provides sqlalchemy + asyncpg)",
    "mysql": "pip install 'serverops[db]' (provides sqlalchemy + aiomysql)",
    "sqlite": "pip install 'serverops[db]' (provides sqlalchemy + aiosqlite)",
    "redis": "pip install 'serverops[db]' (provides redis)",
    "clickhouse": "pip install 'serverops[db]' (provides clickhouse-connect)",
    "elasticsearch": "pip install 'serverops[elasticsearch]' (provides elasticsearch)",
}


class ConnectorRegistry:
    """Owns config, safety policy, audit log, and the connector cache."""

    def __init__(self, config: ServerOpsConfig) -> None:
        self.config = config
        self.settings = config.settings
        self.safety = SafetyPolicy(config.settings)
        self.audit = AuditLog(config.settings.audit_log)
        self._cache: dict[str, AsyncConnector] = {}

    @classmethod
    def from_config_path(cls, explicit: str | None = None) -> ConnectorRegistry:
        return cls(load_config(explicit))

    # -- introspection ---------------------------------------------------

    def connection_names(self) -> list[str]:
        return list(self.config.connections.keys())

    def connections_view(self) -> MappingProxyType[str, Any]:
        return MappingProxyType(self.config.connections)

    def get_profile(self, name: str) -> Any:
        try:
            return self.config.connections[name]
        except KeyError as e:
            raise UnknownConnection(
                f"Unknown connection '{name}'. Configured: "
                f"{', '.join(self.connection_names()) or '(none)'}"
            ) from e

    def effective_read_only(self, name: str) -> bool:
        profile = self.get_profile(name)
        return self.safety.effective_read_only(profile.read_only)

    # -- connector lifecycle --------------------------------------------

    async def get(self, name: str) -> AsyncConnector:
        """Return the cached connector for ``name``, building + connecting on first use."""
        cached = self._cache.get(name)
        if cached is not None:
            return cached
        profile = self.get_profile(name)
        connector = self._build(name, profile)
        await connector.connect()
        self._cache[name] = connector
        return connector

    def _build(self, name: str, profile: Any) -> AsyncConnector:
        module_name = _KIND_TO_MODULE[profile.kind]
        try:
            module = importlib.import_module(module_name)
        except ImportError as e:  # optional extra not installed
            raise MissingDependency(_INSTALL_HINT[profile.kind]) from e
        return module.build(name, profile)

    async def invalidate(self, name: str) -> None:
        """Close and drop the cached connector for ``name``.

        Used after a timed-out operation: the underlying connection may be
        stuck in a cancelled state, so the next ``get`` rebuilds it fresh.
        Unknown names are a no-op.
        """
        connector = self._cache.pop(name, None)
        if connector is not None:
            with contextlib.suppress(Exception):
                await connector.close()

    async def close_all(self) -> None:
        """Best-effort teardown of every cached connector."""
        for connector in list(self._cache.values()):
            with contextlib.suppress(Exception):
                await connector.close()
        self._cache.clear()
