"""Config loading: resolve path, interpolate ``${ENV}``, validate with pydantic."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .errors import ConfigError
from .models import ServerOpsConfig

#: Matches ``${VAR_NAME}`` for environment interpolation.
_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

#: Default search path when neither ``--config`` nor ``SERVEROPS_CONFIG`` is set.
DEFAULT_CONFIG_PATHS: tuple[Path, ...] = (
    Path.home() / ".serverops" / "config.yaml",
    Path.home() / ".serverops" / "config.yml",
)


def resolve_config_path(explicit: str | None = None) -> Path:
    """Return the config path to use, or raise ``ConfigError`` if none found."""
    if explicit:
        path = Path(explicit).expanduser()
        if not path.exists():
            raise ConfigError(f"Config file not found: {path}")
        return path

    env_value = os.environ.get("SERVEROPS_CONFIG")
    if env_value:
        path = Path(env_value).expanduser()
        if not path.exists():
            raise ConfigError(f"Config file not found (SERVEROPS_CONFIG): {path}")
        return path

    for path in DEFAULT_CONFIG_PATHS:
        if path.exists():
            return path

    raise ConfigError(
        "No serverOps config found. Set SERVEROPS_CONFIG, pass --config, "
        f"or create one at {DEFAULT_CONFIG_PATHS[0]} (see config/servers.example.yaml)."
    )


def _interpolate(value: Any) -> Any:
    """Recursively replace ``${VAR}`` with ``os.environ[VAR]``.

    Unset variables are left as-is (so unused connections with missing secrets
    do not prevent startup; they will fail clearly on first use).
    """
    if isinstance(value, str):
        def repl(match: re.Match[str]) -> str:
            name = match.group(1)
            return os.environ.get(name, match.group(0))

        return _ENV_REF.sub(repl, value)
    if isinstance(value, dict):
        return {k: _interpolate(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate(v) for v in value]
    return value


def load_config(explicit: str | None = None) -> ServerOpsConfig:
    """Load, interpolate, and validate the config. Raises ``ConfigError``."""
    path = resolve_config_path(explicit)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ConfigError(f"Invalid YAML in {path}:\n{e}") from e
    except OSError as e:
        raise ConfigError(f"Could not read config {path}: {e}") from e

    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigError(
            f"Config root must be a mapping, got {type(raw).__name__} in {path}"
        )

    interpolated = _interpolate(raw)
    try:
        return ServerOpsConfig.model_validate(interpolated)
    except ValidationError as e:
        raise ConfigError(f"Invalid config in {path}:\n{e}") from e
