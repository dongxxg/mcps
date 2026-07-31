"""Shared pytest fixtures for excelOps.

xlsx fixtures are generated on the fly (openpyxl) into per-test ``tmp_path`` so
the repo never carries binary blobs. The big-file smoke fixture is generated
lazily (see test_acceptance) to keep the common run fast.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from openpyxl import Workbook


@pytest.fixture
def sample_workbook(tmp_path: Path) -> Path:
    """Multi-sheet workbook ``[orders, Summary, Data]``.

    ``orders`` has header ``[region, amount]`` + 3 data rows used by the
    closed-loop and enumeration tests.
    """
    p = tmp_path / "sample.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "orders"
    ws.append(["region", "amount"])
    ws.append(["east", 100])
    ws.append(["west", 200])
    ws.append(["east", 50])

    ws2 = wb.create_sheet("Summary")
    ws2.append(["total", 350])

    ws3 = wb.create_sheet("Data")
    ws3.append(["note", "x"])

    wb.save(p)
    return p


@pytest.fixture
def ragged_header_workbook(tmp_path: Path) -> Path:
    """Duplicate header name + a ragged (short) last row.

    Header ``[name, name, amount]``; data: a full row + a 2-cell row in a
    3-column sheet — exercises both header normalization and ragged-row padding.
    """
    p = tmp_path / "ragged.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "sh"
    ws.append(["name", "name", "amount"])
    ws.append(["a", "b", 1])
    ws.append(["c", "d"])  # ragged: only 2 cells where 3 are expected
    wb.save(p)
    return p


@pytest.fixture
def mixed_types_workbook(tmp_path: Path) -> Path:
    """date / nullable / float / text columns for type-fidelity tests."""
    p = tmp_path / "mixed.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "mt"
    ws.append(["d", "nullable", "flt", "txt"])
    ws.append([date(2026, 1, 1), None, 1.5, "hello"])
    ws.append([date(2026, 1, 2), 5, 2.5, "world"])
    wb.save(p)
    return p


@pytest.fixture
def corrupt_xlsx(tmp_path: Path) -> Path:
    """A plain-text file that is not a valid xlsx (zip) archive."""
    p = tmp_path / "corrupt.xlsx"
    p.write_text("this is not an xlsx file", encoding="utf-8")
    return p
