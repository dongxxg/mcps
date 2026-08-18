"""Center-zone data table — QTableView + pagination + operation log."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt  # type: ignore[import-untyped]
from PySide6.QtWidgets import (  # type: ignore[import-untyped]
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTableView,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from excelops.backends.models import SheetData

from ..models.paginated_model import PaginatedModel
from .delegate import CellDelegate


class DataTable(QWidget):
    """Paginated data viewer with an auto-scrolling operation log."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = PaginatedModel(parent=self)
        self._table = QTableView()
        self._table.setModel(self._model)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._table.setShowGrid(True)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setStyleSheet("QTableView { outline: none; }")

        self._delegate = CellDelegate(parent=self)
        self._table.setItemDelegate(self._delegate)

        # Pager controls
        self._btn_first = QPushButton("首页")
        self._btn_prev = QPushButton("上一页")
        self._btn_next = QPushButton("下一页")
        self._btn_last = QPushButton("末页")
        self._label_page = QLabel("1/1")
        self._label_total = QLabel("共 0 行")

        # Placeholder / empty message
        self._empty_label = QLabel("无数据")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet("color: #999; font-size: 14px; padding: 40px;")
        self._empty_label.setVisible(False)

        # Operation log — auto-scrolling, fixed-height bottom strip
        self._log_label = QLabel("操作日志")
        self._log_label.setStyleSheet(
            "font-size: 11px; color: #555; font-weight: bold; padding: 2px 4px;"
        )
        self._log_browser = QTextBrowser()
        self._log_browser.setReadOnly(True)
        self._log_browser.setOpenExternalLinks(True)
        self._log_browser.setStyleSheet(
            "QTextBrowser { "
            "background: #FAFAFA; "
            "border: 1px solid #E0E0E0; "
            "border-radius: 4px; "
            "font-family: Consolas, Menlo, monospace; "
            "font-size: 11px; "
            "padding: 4px; "
            "}"
        )
        log_widget = QWidget()
        log_layout = QVBoxLayout(log_widget)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(2)
        log_layout.addWidget(self._log_label)
        log_layout.addWidget(self._log_browser)

        # Wire pagination
        self._btn_first.clicked.connect(lambda: self._model.jump_to_page(1))
        self._btn_prev.clicked.connect(self._model.prev_page)
        self._btn_next.clicked.connect(self._model.next_page)
        self._btn_last.clicked.connect(self._goto_last)

        self._model.dataChanged.connect(self._refresh_pager)
        self._model.layoutChanged.connect(self._refresh_pager)

        pager = QHBoxLayout()
        pager.addWidget(self._btn_first)
        pager.addWidget(self._btn_prev)
        pager.addWidget(self._label_page)
        pager.addWidget(self._btn_next)
        pager.addWidget(self._btn_last)
        pager.addSpacing(16)
        pager.addWidget(self._label_total)
        pager.addStretch()

        # Vertical splitter: table (grows) | pager + log (fixed-ish)
        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(4)
        bottom_layout.addLayout(pager)
        bottom_layout.addWidget(log_widget)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self._table)
        splitter.addWidget(bottom_widget)
        splitter.setSizes([400, 180])

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(splitter)
        self.setLayout(layout)

        self.append_log("就绪")

    @property
    def model(self) -> PaginatedModel:
        return self._model

    @property
    def table_view(self) -> QTableView:
        return self._table

    def append_log(self, message: str, level: str = "INFO") -> None:
        """Append a timestamped entry to the operation log (auto-scrolls)."""
        ts = datetime.now().strftime("%H:%M:%S")
        level_style = {
            "INFO": "#1A73E8",
            "OK": "#1E8E3E",
            "WARN": "#E37400",
            "ERROR": "#D93025",
        }.get(level, "#1A73E8")
        self._log_browser.append(
            f'<span style="color:#888">[{ts}]</span> '
            f'<span style="color:{level_style};font-weight:bold">[{level}]</span> '
            f"{message}"
        )

    def set_data(self, sheet_data: SheetData | None) -> None:
        """Replace the displayed data and reset to page 1."""
        self._model.set_data(sheet_data)
        if sheet_data is None or len(sheet_data.columns) == 0 or len(sheet_data.rows) == 0:
            self._empty_label.setVisible(True)
            self._empty_label.setText("无数据")
            self._delegate.set_columns(())
        else:
            self._empty_label.setVisible(False)
            self._delegate.set_columns(sheet_data.columns)
        self._refresh_pager()

    def set_empty_message(self, message: str) -> None:
        """Show a message in the empty state (e.g. '无匹配结果')."""
        self._empty_label.setText(message)
        self._empty_label.setVisible(True)

    def _goto_last(self) -> None:
        self._model.jump_to_page(self._model.total_pages)

    def _refresh_pager(self) -> None:
        self._label_page.setText(f"{self._model.current_page}/{self._model.total_pages}")
        self._label_total.setText(f"共 {self._model.total_rows} 行")
        if self._model.total_rows > 0 and self._model.rowCount(None) == 0:
            self._empty_label.setVisible(True)
            self._empty_label.setText("无数据")