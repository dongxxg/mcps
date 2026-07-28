"""Exception hierarchy.

Every error that can reach an MCP tool call is a subclass of ``ServerOpsError``;
its message is safe to surface to the LLM/client (secrets are scrubbed by the
tool-layer redaction decorator before it ever gets there).
"""

from __future__ import annotations


class ServerOpsError(Exception):
    """Base class. ``str(self)`` is intended for end-user/LLM display."""


class ConfigError(ServerOpsError):
    """Configuration file is missing, unreadable, or failed validation."""


class UnknownConnection(ServerOpsError):
    """A tool referenced a connection name that is not in the config."""


class MissingDependency(ServerOpsError):
    """A connector's optional dependency (extra) is not installed."""


class ConnectionFailed(ServerOpsError):
    """Connecting to (or operating on) a remote service failed."""


class SafetyError(ServerOpsError):
    """An operation was blocked by the safety layer (read-only / denylist)."""
