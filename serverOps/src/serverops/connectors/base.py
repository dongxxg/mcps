"""The async connector interface every backend implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class HealthStatus:
    """Result of a best-effort liveness probe of a remote service."""

    healthy: bool
    detail: str = ""


class AsyncConnector(ABC):
    """Base class for all remote-service connectors.

    Concrete classes add their own operation methods (``exec``, ``query``, …).
    Instances are created lazily by ``ConnectorRegistry`` and cached per name.
    """

    kind: str = "base"

    def __init__(self, name: str, profile) -> None:  # profile typed loosely to avoid import cycle
        self.name = name
        self.profile = profile

    @abstractmethod
    async def connect(self) -> None:
        """Establish the underlying connection (lazy heavy-imports go here)."""

    @abstractmethod
    async def health(self) -> HealthStatus:
        """Return a best-effort liveness probe without raising."""

    @abstractmethod
    async def close(self) -> None:
        """Release the underlying connection."""
