"""Secret scrubbing for logs and error messages.

Strips credentials embedded in connection URLs and ``password=...``/``token=...``
style key-value pairs. Used before anything is written to the audit log or
returned to an MCP client.
"""

from __future__ import annotations

import re

# postgres://user:secret@host/db  ->  postgres://user:***@host/db
_URL_CREDENTIALS = re.compile(r"(://[^/\s:@]+:)([^@\s]+)(@)")

# password=hunter2 / api_key: abc / token=xyz  ->  password=***
_KV_SECRET = re.compile(
    r"((?:password|passwd|secret|token|api[_-]?key|private[_-]?key)\s*[=:]\s*)(\S+)",
    re.IGNORECASE,
)

_REDACTED = "***"


def redact(text: str) -> str:
    """Return ``text`` with embedded credentials replaced by ``***``."""
    if not text:
        return text
    text = _URL_CREDENTIALS.sub(lambda m: f"{m.group(1)}{_REDACTED}{m.group(3)}", text)
    text = _KV_SECRET.sub(lambda m: f"{m.group(1)}{_REDACTED}", text)
    return text
