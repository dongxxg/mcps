"""Exception hierarchy for excelOps.

Every error that can reach a future MCP tool call is a subclass of
``ExcelOpsError``; its message is safe to surface (Phase 2 will scrub it via a
redaction decorator before it ever reaches the LLM/client). The full subclass
set is established once, here in Phase 1 — including placeholders such as
``SafetyError`` that are not raised yet — so Phase 2 code can ``except`` and
import them without raise sites being touched (mirrors serverOps's flat tree).
"""

class ExcelOpsError(Exception):
    """Base class. ``str(self)`` is intended for end-user/LLM display."""


class ReadError(ExcelOpsError):
    """Reading an xlsx workbook/sheet failed (missing file, missing sheet, ...)."""


class WriteError(ExcelOpsError):
    """Writing an xlsx workbook failed (invalid input, unwritable path, ...)."""


class AnalyzeError(ExcelOpsError):
    """A SQL analysis operation failed (invalid SQL, session closed, ...)."""


class UnsupportedFormat(ExcelOpsError):
    """The given file is not a valid/parseable xlsx (wrong type or corrupted)."""


class FileLocked(ExcelOpsError):
    """The target file is locked (e.g. open in Excel) after short retries."""


class MissingDependency(ExcelOpsError):
    """An optional extra (``[duckdb]``) is required but not installed."""


class SafetyError(ExcelOpsError):
    """An operation was blocked by the safety layer (placeholder — Phase 2)."""
