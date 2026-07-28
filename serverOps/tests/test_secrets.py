"""Secrets file loader: dotenv parsing, path resolution, override policy, and
end-to-end flow into config ``${VAR}`` interpolation."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from serverops.config import load_config
from serverops.errors import ConfigError
from serverops.secrets import load_secrets, parse_dotenv, resolve_secrets_path

# -- parse_dotenv -----------------------------------------------------------


def test_parse_basic() -> None:
    assert parse_dotenv("FOO=bar\nBAZ=1\n") == {"FOO": "bar", "BAZ": "1"}


def test_parse_export_prefix() -> None:
    assert parse_dotenv("export FOO=bar\n") == {"FOO": "bar"}


def test_parse_single_and_double_quotes() -> None:
    text = "A='hello world'\nB=\"p@ss 'q'\"\n"
    assert parse_dotenv(text) == {"A": "hello world", "B": "p@ss 'q'"}


def test_parse_comments_and_blanks_ignored() -> None:
    text = "# a comment\n\nKEY=val\n   # indented comment\n"
    assert parse_dotenv(text) == {"KEY": "val"}


def test_parse_inline_hash_preserved_in_value() -> None:
    # Secrets routinely contain '#'; inline comments are NOT supported on purpose.
    assert parse_dotenv("PW=ab#cd\n") == {"PW": "ab#cd"}


def test_parse_empty_value() -> None:
    assert parse_dotenv("EMPTY=\n") == {"EMPTY": ""}


def test_parse_last_key_wins_on_duplicate() -> None:
    assert parse_dotenv("K=1\nK=2\n") == {"K": "2"}


@pytest.mark.parametrize("line", ["just-a-key", "=nokey", "1BAD=v", "KE Y=v"])
def test_parse_malformed_raises(line: str) -> None:
    with pytest.raises(ConfigError):
        parse_dotenv(line + "\n")


# -- resolve_secrets_path ---------------------------------------------------


def test_resolve_explicit_path(tmp_path: Path) -> None:
    f = tmp_path / ".env"
    f.write_text("X=1\n", encoding="utf-8")
    assert resolve_secrets_path(str(f)) == f


def test_resolve_explicit_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        resolve_secrets_path(str(tmp_path / "nope.env"))


def test_resolve_via_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = tmp_path / ".env"
    f.write_text("X=1\n", encoding="utf-8")
    monkeypatch.setenv("SERVEROPS_SECRETS", str(f))
    assert resolve_secrets_path() == f


def test_resolve_env_var_missing_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVEROPS_SECRETS", str(tmp_path / "ghost.env"))
    with pytest.raises(ConfigError):
        resolve_secrets_path()


def test_resolve_next_to_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Isolate $HOME so the ~/.serverops/.env default can't interfere.
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "elsewhere")
    cfg = tmp_path / "servers.yaml"
    cfg.write_text("connections: {}\n", encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text("X=1\n", encoding="utf-8")
    assert resolve_secrets_path(config_path=cfg) == env_file


def test_resolve_in_config_parent_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Project-root layout: config in ./config/, .env one level up.
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "elsewhere")
    project = tmp_path / "proj"
    (project / "config").mkdir(parents=True)
    cfg = project / "config" / "servers.yaml"
    cfg.write_text("connections: {}\n", encoding="utf-8")
    env_file = project / ".env"
    env_file.write_text("X=1\n", encoding="utf-8")
    assert resolve_secrets_path(config_path=cfg) == env_file


def test_resolve_none_when_nothing_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "elsewhere")
    cfg = tmp_path / "servers.yaml"
    cfg.write_text("connections: {}\n", encoding="utf-8")
    assert resolve_secrets_path(config_path=cfg) is None


# -- load_secrets override policy ------------------------------------------


def test_load_populates_clean_environ(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("FOO=bar\nBAZ=1\n", encoding="utf-8")
    env: dict[str, str] = {}
    applied = load_secrets(explicit=str(env_file), environ=env)
    assert env == {"FOO": "bar", "BAZ": "1"}
    assert applied == {"FOO": "bar", "BAZ": "1"}


def test_load_does_not_override_existing(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("FOO=from_file\n", encoding="utf-8")
    env = {"FOO": "from_env"}
    applied = load_secrets(explicit=str(env_file), environ=env)
    assert env["FOO"] == "from_env"
    assert applied == {}


def test_load_mixed_override_and_set(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("KEEP=from_env_value\nNEW=from_file\n", encoding="utf-8")
    env = {"KEEP": "from_env_value"}
    applied = load_secrets(explicit=str(env_file), environ=env)
    assert env == {"KEEP": "from_env_value", "NEW": "from_file"}
    assert applied == {"NEW": "from_file"}


def test_load_no_file_is_noop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "elsewhere")
    cfg = tmp_path / "servers.yaml"
    cfg.write_text("connections: {}\n", encoding="utf-8")
    env: dict[str, str] = {}
    assert load_secrets(config_path=cfg, environ=env) == {}
    assert env == {}


def test_load_quiet_does_not_print(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("FOO=bar\n", encoding="utf-8")
    load_secrets(explicit=str(env_file), environ={}, quiet=True)
    assert capsys.readouterr().err == ""


# -- end-to-end: .env -> ${VAR} interpolation -> validated config -----------


def test_secrets_flow_into_config_interpolation(
    isolated_env: Path, tmp_path: Path
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("ANALYTICS_DB_URL=postgresql://u:secret@h/db\n", encoding="utf-8")
    cfg_path = tmp_path / "c.yaml"
    cfg_path.write_text(
        'connections:\n  db:\n    kind: postgres\n    url: "${ANALYTICS_DB_URL}"\n',
        encoding="utf-8",
    )
    try:
        # load_secrets mutates the real os.environ; clean up explicitly below.
        load_secrets(explicit=str(env_file), config_path=cfg_path, quiet=True)
        cfg = load_config(cfg_path)
        assert cfg.connections["db"].url == "postgresql://u:secret@h/db"
    finally:
        os.environ.pop("ANALYTICS_DB_URL", None)
