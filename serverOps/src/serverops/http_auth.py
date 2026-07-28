"""Optional bearer-token auth for the HTTP transport.

A single shared token, compared in constant time. Configure by setting
``SERVEROPS_HTTP_TOKEN`` (or the env var named in ``SERVEROPS_HTTP_TOKEN_ENV``)
and running with ``--transport http``. Without a token, the HTTP transport is
unauthenticated — only suitable for trusted/local networks.
"""

from __future__ import annotations

import hmac

from fastmcp.server.auth import AccessToken, TokenVerifier


class StaticTokenVerifier(TokenVerifier):
    """Authorizes exactly one pre-shared bearer token."""

    def __init__(self, token: str) -> None:
        super().__init__()
        self._expected = token.encode("utf-8")

    async def verify_token(self, token: str) -> AccessToken | None:
        provided = token.encode("utf-8")
        if hmac.compare_digest(provided, self._expected):
            return AccessToken(token=token, client_id="serverops", scopes=[])
        return None
