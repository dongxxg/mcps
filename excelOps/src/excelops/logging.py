"""structlog-based diagnostic logging for excelops.

Encapsulates structlog configuration so backends get a ready-to-use structured
logger that writes JSON lines to a file. This is a **diagnostics /
troubleshooting** facility — it is NOT the Phase 2 audit trail (which is a
policy concern handled at the tool layer).

This module is NOT imported by ``excelops.__init__``; ``import excelops`` never
pulls in structlog. Call ``configure()`` once at startup; ``get_logger()`` is
safe to call before then (logs fall back to structlog's default stderr sink).

Typical use::

    from excelops.logging import configure, get_logger

    configure("excelops.log")
    log = get_logger(__name__)
    log.info("read_sheet.start", path=str(path), sheet=sheet)

Format: one JSON object per line (JSONLines) — timestamp, level, logger name,
event, plus any key-value pairs passed to the log call. Machine-parseable and
grep-friendly.
"""

from __future__ import annotations

import logging
from pathlib import Path

import structlog

__all__ = ["configure", "get_logger", "reset"]


def configure(
    path: str | Path,
    *,
    level: str = "DEBUG",
    console: bool = False,
) -> None:
    """Configure structlog to write structured JSON lines to ``path``.

    Idempotent: each call reconfigures from a clean state, so re-calling with a
    different path/level works as expected.

    Args:
        path: Log file path (opened in append mode, UTF-8).
        level: Minimum log level (DEBUG / INFO / WARNING / ERROR / CRITICAL).
        console: Also emit human-readable, colorized logs to stderr — handy for
            interactive debugging alongside the file.
    """
    # Reset any prior configuration so repeated calls don't stack handlers.
    reset()

    shared: list[structlog.types.Processor] = [
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    structlog.configure(
        processors=[
            *shared,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    file_handler = logging.FileHandler(path, encoding="utf-8")
    file_handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processor=structlog.processors.JSONRenderer(),
            foreign_pre_chain=shared,
        )
    )

    root = logging.getLogger()
    root.addHandler(file_handler)
    root.setLevel(_level_value(level))

    if console:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(
            structlog.stdlib.ProcessorFormatter(
                processor=structlog.dev.ConsoleRenderer(),
                foreign_pre_chain=shared,
            )
        )
        root.addHandler(stream_handler)


def get_logger(name: str | None = None):
    """Return a structlog logger bound to ``name`` (usually ``__name__``).

    Safe to call before ``configure()`` — returns structlog's default logger,
    which writes a one-time configuration reminder to stderr and then logs there.
    """
    return structlog.get_logger(name)


def reset() -> None:
    """Reset structlog to its unconfigured state and clear stdlib handlers.

    Primarily a test helper so each test starts from a clean logging state.
    """
    structlog.reset_defaults()
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)


def _level_value(level: str) -> int:
    value = getattr(logging, level.upper(), None)
    if not isinstance(value, int):
        raise ValueError(
            f"invalid log level {level!r}; "
            f"expected one of DEBUG, INFO, WARNING, ERROR, CRITICAL"
        )
    return value
