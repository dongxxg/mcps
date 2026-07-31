"""Tests for the exception hierarchy (errors.py).

Every error that can reach a future MCP tool call is a subclass of
``ExcelOpsError``. Locking the full subclass set + import paths now (Phase 1)
means Phase 2 redaction / audit decorators can rely on a single ``except
ExcelOpsError`` without chasing raise sites later.
"""

from __future__ import annotations

import pytest

from excelops.errors import (
    AnalyzeError,
    ExcelOpsError,
    FileLocked,
    MissingDependency,
    ReadError,
    SafetyError,
    UnsupportedFormat,
    WriteError,
)

EXPECTED_SUBCLASSES = [
    ReadError,
    WriteError,
    AnalyzeError,
    UnsupportedFormat,
    FileLocked,
    MissingDependency,
    SafetyError,
]


def test_base_is_exception():
    assert issubclass(ExcelOpsError, Exception)


@pytest.mark.parametrize("exc_type", EXPECTED_SUBCLASSES)
def test_subclasses_inherit_base(exc_type):
    assert issubclass(exc_type, ExcelOpsError)


@pytest.mark.parametrize("exc_type", EXPECTED_SUBCLASSES)
def test_subclasses_carry_message(exc_type):
    err = exc_type("boom")
    assert str(err) == "boom"
    # Raising and catching via the base must work for every subclass.
    with pytest.raises(ExcelOpsError):
        raise exc_type("boom")


def test_all_expected_subclasses_present():
    names = {c.__name__ for c in EXPECTED_SUBCLASSES}
    assert names == {
        "ReadError",
        "WriteError",
        "AnalyzeError",
        "UnsupportedFormat",
        "FileLocked",
        "MissingDependency",
        "SafetyError",
    }
