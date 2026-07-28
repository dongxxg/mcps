"""Shared pytest fixtures."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Strip serverOps env vars so tests don't read the developer's real config."""
    for key in list(os.environ):
        if key.startswith("SERVEROPS_") or key in {"ANALYTICS_DB_URL", "REDIS_URL"}:
            monkeypatch.delenv(key, raising=False)
    return tmp_path


class FakeMCP:
    """Captures @mcp.tool-decorated callables into a dict for direct testing."""

    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self, fn=None, **_kwargs):
        if callable(fn):
            self.tools[fn.__name__] = fn
            return fn

        def deco(f):
            self.tools[f.__name__] = f
            return f

        return deco

    def custom_route(self, *_a, **_k):
        def deco(f):
            return f

        return deco


@pytest.fixture
def fake_mcp() -> FakeMCP:
    return FakeMCP()
