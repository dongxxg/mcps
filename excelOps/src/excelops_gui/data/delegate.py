"""Cell rendering delegate — formats dates and numbers for the data table."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from PySide6.QtCore import QModelIndex  # type: ignore[import-untyped]
from PySide6.QtGui import QColor, QPainter  # type: ignore[import-untyped]
from PySide6.QtWidgets import QStyledItemDelegate  # type: ignore[import-untyped]

_PROVENANCE = ("__file__", "__sheet__", "__match_field__", "__priority__")


class CellDelegate(QStyledItemDelegate):
    """Render common cell types with user-friendly formatting."""

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self._columns: tuple[str, ...] = ()

    def set_columns(self, columns: tuple[str, ...]) -> None:
        self._columns = columns

    def displayText(self, value: Any, locale: Any = None) -> str:
        if value is None:
            return ""
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        if isinstance(value, date):
            return value.strftime("%Y-%m-%d")
        if isinstance(value, float):
            if value.is_integer():
                return f"{int(value)}"
            return f"{value:,.6f}".rstrip("0").rstrip(".")
        if isinstance(value, bool):
            return "✓" if value else "✗"
        return str(value)

    def paint(
        self,
        painter: QPainter,
        option: Any,
        index: QModelIndex,
    ) -> None:
        if index.column() >= len(self._columns):
            super().paint(painter, option, index)
            return

        col_name = self._columns[index.column()]
        if col_name in _PROVENANCE:
            painter.save()
            painter.setBrush(QColor("#FFF8E1"))
            painter.drawRect(option.rect)
            painter.restore()

        super().paint(painter, option, index)

    def createEditor(self, parent: Any, option: Any, index: QModelIndex) -> None:  # type: ignore[override]
        # Data view is read-only; no inline editing.
        pass