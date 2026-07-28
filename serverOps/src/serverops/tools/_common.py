"""Shared helpers for tool modules."""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import Any

from ..errors import ServerOpsError
from ..redaction import redact


def redacted(
    fn: Callable[..., Awaitable[Any]],
) -> Callable[..., Awaitable[Any]]:
    """Wrap a tool coroutine so unexpected errors become redacted ``ServerOpsError``.

    ``ServerOpsError`` subclasses pass through unchanged (their messages are
    already clean); any other exception is converted and scrubbed of secrets so
    a stray driver/connection error can never leak credentials to the client.
    """

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await fn(*args, **kwargs)
        except ServerOpsError:
            raise
        except Exception as e:  # noqa: BLE001 - intentional boundary conversion
            raise ServerOpsError(redact(str(e) or type(e).__name__)) from e

    return wrapper
