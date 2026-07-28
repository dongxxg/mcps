"""Profile validation and discriminated-union dispatch."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from serverops.models import (
    DATABASE_KINDS,
    PostgresProfile,
    ServerOpsConfig,
    Settings,
    SSHProfile,
)


def test_ssh_profile_defaults() -> None:
    p = SSHProfile(host="h", user="u")
    assert p.kind == "ssh"
    assert p.port == 22
    assert p.known_hosts == "strict"
    assert p.read_only is False


def test_ssh_profile_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        SSHProfile(host="h", user="u", bogus=1)  # type: ignore[call-arg]


def test_db_profiles_carry_url() -> None:
    p = PostgresProfile(url="postgresql://u:p@h/db")
    assert p.kind == "postgres"
    assert frozenset({"postgres", "mysql", "sqlite", "redis", "clickhouse", "elasticsearch"}) == DATABASE_KINDS


def test_discriminated_union_routes_by_kind() -> None:
    cfg = ServerOpsConfig.model_validate(
        {
            "connections": {
                "a": {"kind": "ssh", "host": "h", "user": "u"},
                "b": {"kind": "postgres", "url": "postgresql://u:p@h/db"},
                "c": {"kind": "redis", "url": "redis://h"},
            }
        }
    )
    assert isinstance(cfg.connections["a"], SSHProfile)
    assert isinstance(cfg.connections["b"], PostgresProfile)
    assert cfg.connections["c"].kind == "redis"


def test_settings_default_denylist_present() -> None:
    s = Settings()
    assert s.ssh_command_denylist
    assert any("rm" in p for p in s.ssh_command_denylist)
    assert s.read_only is False
