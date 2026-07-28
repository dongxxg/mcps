"""Structured JSONL audit log.

One line per audited operation: ``{ts, pid, connection, operation, status, detail}``.
Failures to write are swallowed deliberately — auditing must never break an
operation, only record best-effort.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path


class AuditLog:
    """Append-only JSONL audit log. No-op when ``path`` is falsy."""

    def __init__(self, path: str | None) -> None:
        self.enabled = bool(path)
        self.path: Path | None = Path(path).expanduser() if self.enabled else None
        self._lock = threading.Lock()

    def record(
        self,
        *,
        connection: str,
        operation: str,
        status: str,
        detail: str = "",
    ) -> None:
        if not self.enabled:
            return
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "pid": os.getpid(),
            "connection": connection,
            "operation": operation,
            "status": status,
            "detail": detail,
        }
        line = json.dumps(entry, ensure_ascii=False)
        with self._lock:
            try:
                assert self.path is not None  # for type checkers
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            except OSError:
                # Audit is best-effort: never let logging raise into the tool path.
                pass
