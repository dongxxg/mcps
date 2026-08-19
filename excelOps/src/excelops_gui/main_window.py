"""Three-zone MainWindow — navigation | data | operation panels."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt  # type: ignore[import-untyped]
from PySide6.QtWidgets import (  # type: ignore[import-untyped]
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from excelops.backends.models import SheetData

from .data.data_table import DataTable
from .navigation import NavigationTree
from .panels import PanelContext, get_panel, registered_panels
from .panels.search import SearchPanel
from .workers import ExportWorker, LoadSheetWorker, SearchWorker


class MainWindow(QMainWindow):
    """Top-level window for the excelOps desktop client."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("excelOps — 桌面搜索")
        self.resize(1280, 720)

        self._active_file: str | None = None
        self._active_sheet: str | None = None
        self._current_sheet_data: SheetData | None = None
        self._panels: dict[str, object] = {}
        self._load_worker = None
        self._search_worker = None
        self._export_worker = None

        self._toolbar = self._build_toolbar()
        self._splitter = self._build_splitter()
        status_bar = self.statusBar()

        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(self._toolbar)
        central_layout.addWidget(self._splitter)
        self.setCentralWidget(central)

        self._progress = QProgressBar()
        self._progress.setFixedHeight(2)
        self._progress.setRange(0, 100)
        self._progress.setVisible(False)
        status_bar.addPermanentWidget(self._progress)
        self._status_label = QLabel("就绪")
        status_bar.addPermanentWidget(self._status_label, 1)

    # ─── toolbar ───────────────────────────────────────────────────────────

    def _build_toolbar(self) -> QToolBar:
        tb = QToolBar()
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)

        open_action = tb.addAction("打开文件")
        open_action.triggered.connect(lambda: self._navigation._on_open_file())

        self._file_label = QLabel("未打开文件")
        self._file_label.setStyleSheet("font-weight: bold; color: #333; padding: 0 8px;")
        tb.addWidget(self._file_label)

        tb.addSeparator()

        export_action = tb.addAction("导出")
        export_action.triggered.connect(self._on_export)
        return tb

    # ─── splitter (three zones) ────────────────────────────────────────────

    def _build_splitter(self) -> QSplitter:
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self._navigation = NavigationTree()
        self._navigation.sheet_selected.connect(self._on_sheet_selected)
        self._navigation.directory_selected.connect(self._on_directory_selected)

        self._data_table = DataTable()

        panel_zone = self._build_panel_zone()

        splitter.addWidget(self._navigation)
        splitter.addWidget(self._data_table)
        splitter.addWidget(panel_zone)
        splitter.setSizes([220, 520, 360])

        self._refresh_panel_tabs()
        return splitter

    # ─── right panel zone ──────────────────────────────────────────────────

    def _build_panel_zone(self) -> QWidget:
        widget = QWidget()
        widget_layout = QVBoxLayout(widget)
        widget_layout.setContentsMargins(0, 0, 0, 0)
        self._tab = QTabWidget()
        widget_layout.addWidget(self._tab)
        return widget

    def _refresh_panel_tabs(self) -> None:
        for name, title in registered_panels().items():
            if name in self._panels:
                continue
            if name == "search":
                panel = SearchPanel()
            else:
                cls = get_panel(name)
                panel = cls()
            self._panels[name] = panel
            self._tab.addTab(panel.build_ui(), title)

        search_panel = self._panels.get("search")
        if isinstance(search_panel, SearchPanel):
            search_panel._btn_search.clicked.connect(self._on_search)
            search_panel._btn_search_dir.clicked.connect(self._on_search)
            search_panel._btn_add_cond.clicked.connect(self._on_add_dir_condition)
            search_panel._btn_dir.clicked.connect(self._on_pick_dir)

    # ─── actions ───────────────────────────────────────────────────────────

    def _on_sheet_selected(self, file_path: str, sheet_name: str) -> None:
        self._active_file = file_path
        self._active_sheet = sheet_name
        self._file_label.setText(f"{Path(file_path).name} / {sheet_name}")
        self._status_label.setText(f"加载 {sheet_name}...")
        self._data_table.append_log(
            f"加载 {Path(file_path).name} / {sheet_name}"
        )

        self._load_worker = LoadSheetWorker(file_path, sheet_name)
        self._load_worker.setParent(self)
        self._load_worker.progress.connect(self._on_load_progress)
        self._load_worker.result.connect(self._on_sheet_loaded)
        self._load_worker.error.connect(self._on_error)
        self._load_worker.finished.connect(
            lambda: setattr(self, "_load_worker", None)
        )
        self._load_worker.start()

    def _on_load_progress(self, percent: int, message: str) -> None:
        self._progress.setVisible(True)
        self._progress.setValue(percent)
        self._status_label.setText(message)

    def _on_sheet_loaded(self, sheet_data: SheetData) -> None:
        self._progress.setVisible(False)
        self._current_sheet_data = sheet_data
        self._data_table.set_data(sheet_data)
        self._data_table.append_log(
            f"已加载 {len(sheet_data.rows)} 行", level="OK"
        )
        search_panel = self._panels.get("search")
        if isinstance(search_panel, SearchPanel):
            search_panel.set_columns(sheet_data.columns)
            search_panel.set_active_sheet(self._active_file, self._active_sheet)
        self._status_label.setText(f"已加载 {len(sheet_data.rows)} 行")

    def _on_directory_selected(self, directory: str) -> None:
        search_panel = self._panels.get("search")
        if isinstance(search_panel, SearchPanel):
            search_panel._dir_edit.setText(directory)

    def _on_search(self) -> None:
        search_panel = self._panels.get("search")
        if not isinstance(search_panel, SearchPanel):
            return
        if search_panel._rd_single.isChecked() and not self._active_file:
            search_panel._status_label.setText("请先打开一个文件")
            return

        ctx = PanelContext(
            file_path=self._active_file,
            sheet_name=self._active_sheet,
            sheet_data=self._current_sheet_data,
            directory=search_panel._dir_edit.text().strip() or None,
        )
        self._status_label.setText("搜索中...")
        self._data_table.table_view.setEnabled(False)
        self._data_table.append_log("开始搜索")

        self._search_worker = SearchWorker(search_panel, ctx)
        self._search_worker.setParent(self)
        self._search_worker.progress.connect(self._on_search_progress)
        self._search_worker.result.connect(self._on_search_result)
        self._search_worker.error.connect(self._on_search_error)
        self._search_worker.finished.connect(
            lambda: setattr(self, "_search_worker", None)
        )
        self._search_worker.start()

    def _on_search_progress(self, percent: int, message: str) -> None:
        self._progress.setVisible(True)
        self._progress.setValue(percent)
        self._status_label.setText(message)

    def _on_search_result(self, result: object) -> None:
        self._progress.setVisible(False)
        self._data_table.table_view.setEnabled(True)
        from .panels.base import PanelResult

        if isinstance(result, PanelResult) and result.sheet_data is not None:
            self._data_table.set_data(result.sheet_data)
            search_panel = self._panels.get("search")
            if isinstance(search_panel, SearchPanel):
                search_panel._status_label.setText(result.message)
            self._data_table.append_log(result.message, level="OK")
            self._status_label.setText(result.message)
        else:
            self._status_label.setText("就绪")
            self._data_table.append_log("搜索完成（无结果）")

    def _on_search_error(self, error: str) -> None:
        self._progress.setVisible(False)
        self._data_table.table_view.setEnabled(True)
        search_panel = self._panels.get("search")
        if isinstance(search_panel, SearchPanel):
            search_panel._status_label.setText(f"错误: {error}")
        self._data_table.append_log(f"搜索失败: {error}", level="ERROR")
        self._status_label.setText(f"搜索失败: {error}")

    def _on_add_dir_condition(self) -> None:
        search_panel = self._panels.get("search")
        if not isinstance(search_panel, SearchPanel):
            return

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(4)

        col_input = QLineEdit()
        col_input.setPlaceholderText("输入字段名")
        val_input = QLineEdit()
        mode_combo = QComboBox()
        mode_combo.addItems(["精确", "模糊"])
        del_btn = QPushButton("×")
        del_btn.setFixedWidth(28)
        del_btn.clicked.connect(lambda: row.setParent(None))

        row_layout.addWidget(col_input)
        row_layout.addWidget(val_input)
        row_layout.addWidget(mode_combo)
        row_layout.addWidget(del_btn)

        search_panel._dir_cond_layout.addWidget(row)
        search_panel._dir_rows.append(row)

    def _on_pick_dir(self) -> None:
        search_panel = self._panels.get("search")
        if not isinstance(search_panel, SearchPanel):
            return
        directory = QFileDialog.getExistingDirectory(self, "选择搜索目录")
        if directory:
            search_panel._dir_edit.setText(directory)

    def _on_export(self) -> None:
        sd = self._data_table.model._sheet_data
        if sd is None or len(sd.rows) == 0:
            QMessageBox.information(self, "导出", "当前无数据可导出")
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出为 Excel",
            "结果.xlsx",
            "Excel 工作簿 (*.xlsx)",
        )
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"

        self._status_label.setText("导出中...")
        self._progress.setVisible(True)
        self._data_table.append_log(f"导出到 {Path(path).name}")

        self._export_worker = ExportWorker(sd, path, "结果")
        self._export_worker.setParent(self)
        self._export_worker.progress.connect(
            lambda p, m: (self._progress.setValue(p), self._status_label.setText(m))
        )
        self._export_worker.result.connect(
            lambda r: (
                self._data_table.append_log(f"导出完成: {r.rows_written} 行", level="OK"),
                self._status_label.setText(f"导出完成: {r.rows_written} 行"),
            )
        )
        self._export_worker.error.connect(
            lambda e: (
                self._data_table.append_log(f"导出失败: {e}", level="ERROR"),
                self._status_label.setText(f"导出失败: {e}"),
            )
        )
        self._export_worker.finished.connect(
            lambda: setattr(self, "_export_worker", None)
        )
        self._export_worker.start()

    def _on_error(self, error: str) -> None:
        self._progress.setVisible(False)
        self._data_table.append_log(error, level="ERROR")
        self._status_label.setText(f"错误: {error}")
        QMessageBox.warning(self, "错误", error)
