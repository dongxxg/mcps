"""excelOps — a pure-Python Excel read → analyze → write library.

Phase 1 capability layer: an openpyxl-based reader, an embedded DuckDB
analyzer, and an xlsxwriter-based writer, glued by a single shared
``SheetData`` type (no pandas required).

Backends are policy-unaware by design — safety / audit / redaction are NOT
handled here, so Phase 2 can wrap them as MCP tools without touching this
layer (mirroring serverOps's connectors → tools seam).

Importing this package does NOT require the optional ``[duckdb]`` extra:
``duckdb`` is imported lazily inside the analyzer, so ``import excelops``
succeeds even when only the pure-Python core is installed.
"""

from .backends.analyzer import Analyzer
from .backends.merger import merge_workbook
from .backends.models import MergeResult, SheetData, SheetMeta, WriteResult
from .backends.reader import list_sheets, read_sheet, sheet_meta
from .backends.writer import write_workbook
from .errors import (
    AnalyzeError,
    CombineError,
    ExcelOpsError,
    FileLocked,
    LookupError,
    MergeError,
    MissingDependency,
    OpsError,
    ProjectError,
    ReadError,
    SafetyError,
    SearchError,
    TransformError,
    UnsupportedFormat,
    WriteError,
)
from .search import search_files

__version__ = "0.1.0"

__all__ = [
    "__version__",
    # models
    "SheetData",
    "SheetMeta",
    "WriteResult",
    "MergeResult",
    # read
    "list_sheets",
    "read_sheet",
    "sheet_meta",
    # analyze (duckdb imported lazily inside Analyzer)
    "Analyzer",
    # write
    "write_workbook",
    # merge
    "merge_workbook",
    # errors
    "ExcelOpsError",
    "OpsError",
    "ReadError",
    "WriteError",
    "AnalyzeError",
    "UnsupportedFormat",
    "FileLocked",
    "MergeError",
    "MissingDependency",
    "SafetyError",
    "CombineError",
    "LookupError",
    "ProjectError",
    "SearchError",
    "TransformError",
    # search
    "search_files",
]
