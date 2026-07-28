"""StaticTokenVerifier: correct token authorizes, others rejected."""

from __future__ import annotations

import pytest

from serverops.http_auth import StaticTokenVerifier


async def test_correct_token_authorizes() -> None:
    verifier = StaticTokenVerifier("s3cret")
    access = await verifier.verify_token("s3cret")
    assert access is not None
    assert access.client_id == "serverops"
    assert access.scopes == []


@pytest.mark.parametrize("bad", ["wrong", "", "S3cret", "s3cret "])
async def test_wrong_token_rejected(bad: str) -> None:
    verifier = StaticTokenVerifier("s3cret")
    assert await verifier.verify_token(bad) is None


def test_create_app_accepts_auth() -> None:
    from fastmcp import FastMCP

    from serverops.models import ServerOpsConfig
    from serverops.registry import ConnectorRegistry
    from serverops.server import create_app

    app = create_app(ConnectorRegistry(ServerOpsConfig()), auth=StaticTokenVerifier("t"))
    assert isinstance(app, FastMCP)
    assert app.auth is not None
