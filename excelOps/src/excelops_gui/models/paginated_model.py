"""Paginated table model — a QAbstractTableModel view over SheetData.

The full ``SheetData`` is held in memory (the library already read it streamingly
with ``read_only=True``), but the model only exposes a *page slice* of the rows.
This keeps ``QTableView`` painting time bounded regardless of source size and
surfaces the classic pager affordance at the bottom of the data zone.

Page indexing is 1-based (``current_page``), matching the UI label ``X/Y``.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import (  # type: ignore[import-untyped]
    QAbstractTableModel,
    QModelIndex,
    Qt,
)
from PySide6.QtWidgets import QWidget  # type: ignore[import-untyped]

from excelops.backends.models import SheetData

DEFAULT_PAGE_SIZE = 500


class PaginatedModel(QAbstractTableModel):
    """Expose a page-sized window into a :class:`excelops.SheetData`."""

    def __init__(self, sheet_data: SheetData | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._sheet_data: SheetData | None = None
        self._current_page: int = 1
        self._page_size = DEFAULT_PAGE_SIZE
        if sheet_data is not None:
            self.set_data(sheet_data)

    # ─── accessors ─────────────────────────────────────────────────────────

    @property
    def total_rows(self) -> int:
        return 0 if self._sheet_data is None else len(self._sheet_data.rows)

    @property
    def total_pages(self) -> int:
        return 1 if self.total_rows == 0 else (self.total_rows + self._page_size - 1) // self._page_size

    @property
    def current_page(self) -> int:
        return self._current_page

    @property
    def page_size(self) -> int:
        return self._page_size

    @page_size.setter
    def page_size(self, value: int) -> None:
        if value <= 0:
            raise ValueError("page_size must be positive")
        self._page_size = value
        self.set_data(self._sheet_data)

    # ─── data setters ──────────────────────────────────────────────────────

    def set_data(self, sheet_data: SheetData | None) -> None:
        """Replace the underlying data and reset to page 1."""
        self._sheet_data = sheet_data
        self._current_page = 1
        self.layoutChanged.emit()

    def row_value(self, row: int, column: int) -> Any:
        """Return the raw cell value at the given page-local (row, column)."""
        if self._sheet_data is None:
            return None
        start = (self._current_page - 1) * self._page_size
        end = start + len(self._page_rows)
        idx = start + row
        if idx < start or idx >= end or column >= len(self._sheet_data.columns):
            return None
        return self._sheet_data.rows[idx][column]

    @property
    def _page_rows(self) -> tuple[tuple, ...]:
        if self._sheet_data is None:
            return ()
        start = (self._current_page - 1) * self._page_size
        return self._sheet_data.rows[start : start + self._page_size]

    # ─── navigation ────────────────────────────────────────────────────────

    def next_page(self) -> bool:
        """Advance to the next page; return ``True`` if the page changed."""
        if self._current_page < self.total_pages:
            self._current_page += 1
            self.layoutChanged.emit()
            return True
        return False

    def prev_page(self) -> bool:
        """Go to the previous page; return ``True`` if the page changed."""
        if self._current_page > 1:
            self._current_page -= 1
            self.layoutChanged.emit()
            return True
        return False

    def jump_to_page(self, page: int) -> bool:
        """Jump to an absolute page; return ``True`` if the page changed."""
        if page < 1 or page > self.total_pages:
            return False
        if page == self._current_page:
            return False
        self._current_page = page
        self.layoutChanged.emit()
        return True

    # ─── QAbstractTableModel interface ─────────────────────────────────────

    def rowCount(self, parent: QModelIndex | None = None) -> int:
        if parent is not None and parent.isValid():
            return 0
        return len(self._page_rows)

    def columnCount(self, parent: QModelIndex | None = None) -> int:
        if parent is not None and parent.isValid():
            return 0
        return 0 if self._sheet_data is None else len(self._sheet_data.columns)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        return self.row_value(index.row(), index.column())

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            if self._sheet_data is None or section >= len(self._sheet_data.columns):
                return None
            return self._sheet_data.columns[section]
        return section + 1
