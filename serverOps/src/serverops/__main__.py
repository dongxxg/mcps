"""CLI entrypoint: ``python -m serverops`` / ``serverops`` console script."""

from __future__ import annotations

import argparse
import os
import sys

from .config import ConfigError, load_config, resolve_config_path
from .registry import ConnectorRegistry
from .secrets import load_secrets
from .server import add_health_route, create_app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="serverops", description="serverOps MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default=os.environ.get("SERVEROPS_TRANSPORT", "stdio"),
        help="Transport protocol (default: stdio; override via SERVEROPS_TRANSPORT).",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("SERVEROPS_HOST", "127.0.0.1"),
        help="Bind host for HTTP transport (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("SERVEROPS_PORT", "8000")),
        help="Bind port for HTTP transport (default: 8000).",
    )
    parser.add_argument(
        "--config",
        default=os.environ.get("SERVEROPS_CONFIG"),
        help="Path to servers.yaml (default: SERVEROPS_CONFIG or ~/.serverops/config.yaml).",
    )
    parser.add_argument(
        "--secrets",
        default=os.environ.get("SERVEROPS_SECRETS"),
        help="Path to a .env secrets file (default: SERVEROPS_SECRETS or .env next to config).",
    )
    return parser


def _http_token() -> str | None:
    env_name = os.environ.get("SERVEROPS_HTTP_TOKEN_ENV", "SERVEROPS_HTTP_TOKEN")
    return os.environ.get(env_name)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        # Resolve config first so the secrets loader can find `.env` next to it,
        # then populate the environment BEFORE interpolation consumes it.
        config_path = resolve_config_path(args.config)
        load_secrets(args.secrets, config_path)
        registry = ConnectorRegistry(load_config(config_path))
    except ConfigError as e:
        print(str(e), file=sys.stderr)
        return 2

    auth = None
    if args.transport == "http":
        token = _http_token()
        if token:
            from .http_auth import StaticTokenVerifier  # lazy: only when a token is set

            auth = StaticTokenVerifier(token)

    mcp = create_app(registry, auth=auth)
    if args.transport == "http":
        add_health_route(mcp)
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        mcp.run(transport="stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
