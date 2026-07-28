"""Config loading: path resolution, env interpolation, validation errors."""

from __future__ import annotations

import pytest

from serverops.config import load_config, resolve_config_path
from serverops.errors import ConfigError


def _write(path, body: str) -> str:
    path.write_text(body, encoding="utf-8")
    return str(path)


def test_load_minimal_config(isolated_env, tmp_path) -> None:
    cfg_path = _write(tmp_path / "c.yaml", "connections: {}\n")
    cfg = load_config(cfg_path)
    assert cfg.connections == {}


def test_env_interpolation(isolated_env, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANALYTICS_DB_URL", "postgresql://u:secret@h/db")
    cfg_path = _write(
        tmp_path / "c.yaml",
        """
connections:
  db:
    kind: postgres
    url: "${ANALYTICS_DB_URL}"
""",
    )
    cfg = load_config(cfg_path)
    assert cfg.connections["db"].url == "postgresql://u:secret@h/db"


def test_unset_env_left_as_literal(isolated_env, tmp_path) -> None:
    cfg_path = _write(
        tmp_path / "c.yaml",
        """
connections:
  db:
    kind: postgres
    url: "${MISSING_VAR}"
""",
    )
    cfg = load_config(cfg_path)
    assert cfg.connections["db"].url == "${MISSING_VAR}"


def test_invalid_kind_rejected(isolated_env, tmp_path) -> None:
    cfg_path = _write(
        tmp_path / "c.yaml",
        """
connections:
  x:
    kind: telnet
    url: "telnet://h"
""",
    )
    with pytest.raises(ConfigError):
        load_config(cfg_path)


def test_explicit_missing_path_raises(isolated_env, tmp_path) -> None:
    with pytest.raises(ConfigError):
        load_config(str(tmp_path / "nope.yaml"))


def test_resolve_falls_back_to_env_var(isolated_env, tmp_path, monkeypatch) -> None:
    p = _write(tmp_path / "env.yaml", "connections: {}\n")
    monkeypatch.setenv("SERVEROPS_CONFIG", p)
    assert resolve_config_path() == _norm(p)


def _norm(p: str):
    from pathlib import Path

    return Path(p).expanduser()
