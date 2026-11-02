"""Pydantic models for connection profiles and global settings.

``ConnectionProfile`` is a discriminated union keyed on ``kind``. Each backend
maps to one or more discriminator values, and the registry dispatches on that
value to build the right connector.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

#: SSH commands refused by default (regex patterns, case-insensitive).
DEFAULT_SSH_DENYLIST: tuple[str, ...] = (
    r"\brm\s+-rf\s+/(?:\s|$)",            # rm -rf /
    r"\bmkfs\b",                           # mkfs.*
    r"\bdd\s+.*of=/dev/",                  # dd ... of=/dev/sdX
    r"\bshutdown\b",
    r"\breboot\b",
    r":\(\)\s*\{\s*:\|:&\s*\}\s*;\s*:",    # classic fork bomb
    r">\s*/dev/sd[a-z]",                   # redirect onto a block device
)

#: Hard ceiling for ``db_query`` result rows, regardless of configuration —
#: results flow into the model context, so an unbounded fetch is a hazard.
QUERY_MAX_ROWS_CAP: int = 2000


# ---------------------------------------------------------------------------
# Connection profiles
# ---------------------------------------------------------------------------

model_config = ConfigDict(extra="forbid")


class _BaseProfile(BaseModel):
    """Fields shared by every connection profile."""

    model_config = ConfigDict(extra="forbid")

    description: str | None = None
    read_only: bool = False


class SSHProfile(_BaseProfile):
    kind: Literal["ssh"] = "ssh"
    host: str
    port: int = 22
    user: str
    key_path: str | None = None
    #: Name of the env var holding the SSH password (alternative to key auth).
    password_env: str | None = None
    #: ``strict`` = require ~/.ssh/known_hosts match; ``ignore`` = accept any
    #: host key (insecure); ``accept-new`` currently behaves like ``strict``.
    known_hosts: Literal["strict", "accept-new", "ignore"] = "strict"


class DockerProfile(_BaseProfile):
    kind: Literal["docker"] = "docker"
    url: str = "unix:///var/run/docker.sock"
    tls_verify: bool = False
    cert_path: str | None = None


class KubernetesProfile(_BaseProfile):
    kind: Literal["kubernetes"] = "kubernetes"
    kubeconfig: str | None = None
    context: str | None = None
    in_cluster: bool = False
    namespace: str = "default"


class _DatabaseProfileBase(_BaseProfile):
    #: Connection URL. Use ``${ENV_VAR}`` to inject a secret from the environment.
    url: str


class PostgresProfile(_DatabaseProfileBase):
    kind: Literal["postgres"] = "postgres"


class MySQLProfile(_DatabaseProfileBase):
    kind: Literal["mysql"] = "mysql"


class SQLiteProfile(_DatabaseProfileBase):
    kind: Literal["sqlite"] = "sqlite"


class RedisProfile(_DatabaseProfileBase):
    kind: Literal["redis"] = "redis"


class ClickHouseProfile(_DatabaseProfileBase):
    #: Query-only by design: db_execute is rejected and db_query accepts only
    #: read statements (SELECT/SHOW/DESCRIBE/...). See connectors/database.py.
    kind: Literal["clickhouse"] = "clickhouse"


class ElasticsearchProfile(_DatabaseProfileBase):
    #: Read-only by design: only search, get, and index-listing tools are exposed.
    #: No write/delete/update operations are ever provided.
    kind: Literal["elasticsearch"] = "elasticsearch"


ConnectionProfile = Annotated[
    SSHProfile
    | DockerProfile
    | KubernetesProfile
    | PostgresProfile
    | MySQLProfile
    | SQLiteProfile
    | RedisProfile
    | ClickHouseProfile
    | ElasticsearchProfile,
    Field(discriminator="kind"),
]


# ---------------------------------------------------------------------------
# Settings + top-level config
# ---------------------------------------------------------------------------

#: All database/backend discriminator values.
DATABASE_KINDS: frozenset[str] = frozenset(
    {"postgres", "mysql", "sqlite", "redis", "clickhouse", "elasticsearch"}
)


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    read_only: bool = False
    ssh_command_denylist: list[str] = Field(default_factory=lambda: list(DEFAULT_SSH_DENYLIST))
    ssh_command_allowlist: list[str] = Field(default_factory=list)
    #: Path to a JSONL audit log. ``None`` disables auditing.
    audit_log: str | None = None
    #: Default row cap applied by ``db_query`` (overridable per call up to
    #: ``QUERY_MAX_ROWS_CAP``).
    query_max_rows: int = Field(default=200, ge=1, le=QUERY_MAX_ROWS_CAP)
    #: Default wall-clock timeout for ``db_query`` in seconds.
    query_timeout_s: float = Field(default=30.0, gt=0)


class ServerOpsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connections: dict[str, ConnectionProfile] = Field(default_factory=dict)
    settings: Settings = Field(default_factory=Settings)
