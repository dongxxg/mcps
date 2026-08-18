"""Left-zone file / sheet tree navigation."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal  # type: ignore[import-untyped]
from PySide6.QtWidgets import (  # type: ignore[import-untyped]
    QFileDialog,
    QHBoxLayout,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from excelops.backends.reader import list_sheets


class NavigationTree(QWidget):
    """File/Sheet tree with an "open file" button."""

    # Emitted when the user selects a sheet: (file_path, sheet_name)
    sheet_selected = Signal(str, str)
    # Emitted when a directory is chosen: (directory_path)
    directory_selected = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setIndentation(16)
        self._tree.itemClicked.connect(self._on_item_clicked)

        self._btn_file = QPushButton("打开文件")
        self._btn_file.setObjectName("primary")
        self._btn_file.clicked.connect(self._on_open_file)
        self._btn_dir = QPushButton("打开目录")
        self._btn_dir.clicked.connect(self._on_open_directory)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self._btn_file)
        btn_row.addWidget(self._btn_dir)

        layout = QVBoxLayout()
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        layout.addLayout(btn_row)
        layout.addWidget(self._tree)
        self.setLayout(layout)

    @property
    def tree(self) -> QTreeWidget:
        return self._tree

    # ─── open actions ──────────────────────────────────────────────────────

    def _on_open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 Excel 文件",
            "",
            "Excel 工作簿 (*.xlsx);;所有文件 (*)",
        )
        if not path:
            return
        self._add_file_to_tree(Path(path))

    def _on_open_directory(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "选择目录")
        if not directory:
            return
        self.directory_selected.emit(directory)
        # Also auto-populate the tree with any xlsx files in the directory
        self._add_directory_to_tree(Path(directory))

    # ─── tree management ───────────────────────────────────────────────────

    def _add_directory_to_tree(self, directory: Path) -> None:
        dir_item = QTreeWidgetItem(self._tree)
        dir_item.setText(0, f"📂 {directory.name}")
        dir_item.setExpanded(True)
        for xlsx in sorted(directory.glob("*.xlsx")):
            if xlsx.is_file():
                self._add_file_to_tree(xlsx, parent=dir_item)

    def _add_file_to_tree(self, path: Path, parent: QTreeWidgetItem | None = None) -> None:
        try:
            sheets = list_sheets(path)
        except Exception:
            return
        file_item = QTreeWidgetItem(parent if parent is not None else self._tree)
        file_item.setText(0, f"📄 {path.name}")
        file_item.setData(0, Qt.ItemDataRole.UserRole, str(path))
        for name in sheets:
            sheet_item = QTreeWidgetItem(file_item)
            sheet_item.setText(0, f"📊 {name}")
            sheet_item.setData(0, Qt.ItemDataRole.UserRole, (str(path), name))
        file_item.setExpanded(True)

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(data, tuple) and len(data) == 2:
            self.sheet_selected.emit(data[0], data[1])

    @property
    def current_file_path(self) -> str | None:
        """Return the file path of the currently selected item (if any)."""
        item = self._tree.currentItem()
        if item is None:
            return None
        return item.data(0, Qt.ItemDataRole.UserRole)
