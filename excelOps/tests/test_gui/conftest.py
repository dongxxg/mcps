# pytest conftest for excelops_gui.
#
# All GUI tests require PySide6; skip the whole suite (with a clear reason)
# when it is not installed, so ``pip install excelops && pytest`` stays green.

from __future__ import annotations

from collections.abc import Iterator

import pytest

pyside6 = pytest.importorskip("PySide6.QtCore")

from pathlib import Path  # noqa: E402  - after importorskip
from PySide6.QtWidgets import QApplication  # noqa: E402  # type: ignore[import-untyped]

from excelops.backends.models import SheetData
from excelops.backends.writer import write_workbook


@pytest.fixture
def app() -> Iterator[QApplication]:
    """Ensure a QApplication instance exists for widget/model construction."""
    qapp = QApplication.instance()
    if qapp is None:
        qapp = QApplication([])
    yield qapp
    # QApplication lives until process exit; sibling tests share it.


def _make_xlsx(path: Path, sheets: dict[str, SheetData]) -> None:
    write_workbook(path, sheets)


@pytest.fixture
def tmp_xlsx(tmp_path: Path) -> Path:
    """Create a sample xlsx with one sheet containing a few rows."""
    path = tmp_path / "sample.xlsx"
    sd = SheetData(
        columns=("编码", "名称", "价格"),
        rows=(
            ("A001", "牛奶", 9.9),
            ("A002", "面包", 5.5),
            ("A003", "牛奶饮品", 12.0),
        ),
    )
    _make_xlsx(path, {"sheet1": sd})
    return path
