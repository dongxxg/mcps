"""Secrets file loader.

Manages every password / key / connection URL in **one** dotenv-style file
(``KEY=VALUE``), loaded into ``os.environ`` BEFORE config interpolation runs.
The existing ``${VAR}`` (DB URLs) and ``password_env`` (SSH) mechanisms then
pick the values up unchanged, so ``servers.yaml`` never needs to hold — or
even know about — the secrets file. The file is a purely additive side-channel.

Resolution order (first hit wins; later steps are skipped once one matches):

  1. ``--secrets`` CLI flag, or ``SERVEROPS_SECRETS`` env var (explicit; the
     path must exist or ``ConfigError`` is raised).
  2. ``.env`` sitting next to the resolved config file.
  3. ``~/.serverops/.env``.
  4. nothing — many connections (key auth, sqlite, local docker) need no secret.

Override policy: a variable already present in the environment is **never**
overwritten. Anything the shell, CI, or the ``.mcp.json`` ``env`` block sets
always wins over the file, so operators can override a value without editing it.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from .errors import ConfigError

#: Default search locations when no explicit path is given.
DEFAULT_SECRETS_PATHS: tuple[Path, ...] = (Path.home() / ".serverops" / ".env",)

#: A legal dotenv key: letter/underscore start, then word chars.
_VALID_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def resolve_secrets_path(
    explicit: str | None = None,
    config_path: Path | None = None,
) -> Path | None:
    """Return the secrets file path to load, or ``None`` if none applies.

    Raises ``ConfigError`` only when a path was named explicitly (CLI flag or
    ``SERVEROPS_SECRETS``) but does not exist — silent skipping is reserved for
    the discovered defaults.
    """
    source = explicit or os.environ.get("SERVEROPS_SECRETS")
    if source:
        path = Path(source).expanduser()
        label = "--secrets" if explicit else "SERVEROPS_SECRETS"
        if not path.exists():
            raise ConfigError(f"Secrets file not found ({label}): {path}")
        return path

    candidates: list[Path] = []
    if config_path is not None:
        cfg_dir = config_path.expanduser().resolve().parent
        candidates.append(cfg_dir / ".env")         # next to the config file
        candidates.append(cfg_dir.parent / ".env")  # one level up (project root)
    candidates.extend(DEFAULT_SECRETS_PATHS)
    for path in candidates:
        if path.exists():
            return path
    return None


def parse_dotenv(text: str) -> dict[str, str]:
    """Parse dotenv ``KEY=VALUE`` lines into a dict.

    - Blank lines and full-line ``#`` comments are ignored.
    - A leading ``export `` is stripped.
    - A value wrapped in matching single/double quotes is unquoted.
    - ``#`` inside a value is preserved (secrets routinely contain ``#``), so
      inline comments are NOT supported — quote values with special characters.

    Raises ``ConfigError`` on a line without ``=`` or with an invalid key.
    """
    result: dict[str, str] = {}
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            raise ConfigError(f"Malformed secrets line {lineno}: expected KEY=VALUE")
        key, _, value = line.partition("=")
        key = key.strip()
        if not _VALID_KEY.fullmatch(key):
            raise ConfigError(f"Malformed secrets line {lineno}: invalid key {key!r}")
        result[key] = _unquote(value.strip())
    return result


def _unquote(value: str) -> str:
    """Strip a single layer of matching surrounding quotes, if present."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def load_secrets(
    explicit: str | None = None,
    config_path: Path | None = None,
    *,
    environ: dict[str, str] | None = None,
    quiet: bool = False,
) -> dict[str, str]:
    """Load the resolved secrets file into the environment without overriding.

    Returns the keys that were actually applied (those not already set). Raises
    ``ConfigError`` if an explicit file is unreadable or malformed. ``environ``
    defaults to ``os.environ`` but may be injected for testing.
    """
    env = environ if environ is not None else os.environ
    path = resolve_secrets_path(explicit, config_path)
    if path is None:
        return {}

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ConfigError(f"Could not read secrets file {path}: {e}") from e

    applied: dict[str, str] = {}
    for key, value in parse_dotenv(text).items():
        if key not in env:
            env[key] = value
            applied[key] = value

    if applied and not quiet:
        # Count + path only — never the values. stderr is safe under stdio MCP.
        print(f"[serverops] loaded {len(applied)} secret(s) from {path}", file=sys.stderr)
    return applied
