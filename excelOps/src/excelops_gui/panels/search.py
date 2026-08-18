"""Search panel — the first registered operation.

Two modes:
    - **Single-file** (default): filter the currently loaded sheet by one
      ``column=value`` predicate (exact or contains). Uses
      ``read_sheet()`` + ``ops.filter()``.
    - **Directory**: priority-ordered multi-condition scan across every
      ``.xlsx`` in a chosen directory. Uses ``search_files()``.

The panel contains zero business logic — it delegates to the ``excelops``
library API. UI construction lives in :meth:`build_ui`; the async execution
lives in :class:`SearchWorker` (``excelops_gui.workers``).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (  # type: ignore[import-untyped]
    QButtonGroup,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from excelops import search_files
from excelops.ops import filter

from .base import BasePanel, PanelContext, PanelResult, register_panel


@register_panel("search", "搜索")
class SearchPanel(BasePanel):
    """Search operation panel.

    The panel exposes two sub-modes toggled by radio buttons at the top. The
    layout is deliberately compact so it fits in the narrow right-hand zone of
    the main window.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__()
        self._parent = parent
        self._columns: tuple[str, ...] = ()
        self._file_path: str | None = None
        self._sheet_name: str | None = None

        # Built widgets (cached so execute() can read them).
        self._col_combo = QComboBox()
        self._value_input = QLineEdit()
        self._mode_combo = QComboBox()
        self._mode_combo.addItems(["精确", "模糊"])
        self._btn_search = QPushButton("搜索")

        self._dir_edit = QLineEdit()
        self._dir_edit.setPlaceholderText("选择目录或输入路径")
        self._btn_dir = QPushButton("选择目录")
        self._btn_add_cond = QPushButton("添加条件")
        self._btn_search_dir = QPushButton("搜索目录")

        # Directory-mode condition rows live here: list of (col, val, mode).
        self._dir_rows: list[QWidget] = []

        self._rd_single = QRadioButton("当前 Sheet")
        self._rd_dir = QRadioButton("目录扫描")
        self._mode_group = QButtonGroup()
        self._mode_group.addButton(self._rd_single)
        self._mode_group.addButton(self._rd_dir)
        self._rd_single.setChecked(True)

        self._limit_spin = QSpinBox()
        self._limit_spin.setRange(0, 100000)
        self._limit_spin.setValue(0)
        self._limit_label = QLabel("最大结果数 (0=全部)")

        self._status_label = QLabel("")

    def set_columns(self, columns: tuple[str, ...] | None) -> None:
        """Populate the column dropdown from the current sheet's headers."""
        self._columns = tuple(columns) if columns else ()
        self._col_combo.clear()
        self._col_combo.addItems(self._columns)

    def set_active_sheet(self, file_path: str | None, sheet_name: str | None) -> None:
        self._file_path = file_path
        self._sheet_name = sheet_name

    # ─── UI construction ───────────────────────────────────────────────────

    def build_ui(self) -> QWidget:
        root = QWidget(self._parent)
        root.setLayout(QVBoxLayout())
        root.layout().setContentsMargins(8, 8, 8, 8)
        root.layout().setSpacing(8)

        # Mode selector
        mode_row = QHBoxLayout()
        mode_row.addWidget(self._rd_single)
        mode_row.addWidget(self._rd_dir)
        self._rd_single.setChecked(True)
        self._root_layout = root.layout()
        root.layout().addLayout(mode_row)

        # ── Single-file sub-panel ─────────────────────────────────────────
        single_widget = QWidget()
        single = QVBoxLayout(single_widget)
        single.setContentsMargins(12, 12, 12, 12)
        single.addWidget(QLabel("列："))
        single.addWidget(self._col_combo)
        single.addWidget(QLabel("值："))
        single.addWidget(self._value_input)
        single.addWidget(QLabel("模式："))
        single.addWidget(self._mode_combo)
        search_row = QHBoxLayout()
        search_row.addWidget(self._btn_search)
        search_row.addStretch()
        single.addLayout(search_row)
        single.addSpacing(8)

        limit_row = QHBoxLayout()
        limit_row.addWidget(self._limit_label)
        limit_row.addWidget(self._limit_spin)
        single.addLayout(limit_row)

        # ── Directory sub-panel ───────────────────────────────────────────
        dir_widget = QWidget()
        directory = QVBoxLayout(dir_widget)
        directory.setContentsMargins(12, 12, 12, 12)
        dir_top = QHBoxLayout()
        dir_top.addWidget(self._dir_edit)
        dir_top.addWidget(self._btn_dir)
        directory.addLayout(dir_top)
        directory.addWidget(QLabel("条件（按优先级，first-hit-wins）"))

        self._dir_cond_area = QScrollArea()
        self._dir_cond_area.setWidgetResizable(True)
        self._dir_cond_widget = QWidget()
        self._dir_cond_layout = QVBoxLayout(self._dir_cond_widget)
        self._dir_cond_layout.setContentsMargins(0, 0, 0, 0)
        self._dir_cond_area.setWidget(self._dir_cond_widget)
        directory.addWidget(self._dir_cond_area)

        dir_btn_row = QHBoxLayout()
        dir_btn_row.addWidget(self._btn_add_cond)
        dir_btn_row.addWidget(self._btn_search_dir)
        directory.addLayout(dir_btn_row)

        root.layout().addWidget(single_widget)
        root.layout().addWidget(dir_widget)
        root.layout().addSpacing(8)

        # Status
        root.layout().addWidget(self._status_label)
        root.layout().addStretch()

        self._status_label.setText("")
        return root

    def _make_group(self, title: str, layout: QVBoxLayout) -> QWidget:
        grp = QWidget()
        grp.setLayout(layout)
        grp.setStyleSheet(
            "QWidget { background: #FAFAFA; border: 1px solid #E0E0E0; "
            "border-radius: 4px; padding: 8px; }"
        )
        return grp

    # ─── execution ─────────────────────────────────────────────────────────

    def execute(self, ctx: PanelContext) -> PanelResult:
        """Execute the currently configured search mode."""
        if self._rd_single.isChecked():
            return self._execute_single(ctx)
        return self._execute_directory(ctx)

    def _execute_single(self, ctx: PanelContext) -> PanelResult:
        if not self._file_path or not self._sheet_name:
            return PanelResult(error="请先打开一个文件")
        if not self._columns:
            return PanelResult(error="当前 sheet 无数据列")
        selected_col = self._col_combo.currentText()
        if not selected_col or selected_col not in self._columns:
            return PanelResult(error="请选择一个有效的列")
        value_text = self._value_input.text()
        mode = "contains" if self._mode_combo.currentIndex() == 1 else "exact"

        if ctx.sheet_data is None:
            return PanelResult(error="当前 sheet 数据不可用")

        target_col = selected_col
        target_val = value_text
        is_contains = mode == "contains"

        def _coerce(val: str, cell: object) -> object | None:
            """将用户输入转为与单元格同类型，用于精确比较。

            openpyxl 保留原生单元格类型（int / float / date），用户输入永远是
            str；返回转换后的值用于 ``cell == result``，失败则返回 None
            表示不匹配。

            bool 优先于 int 判断（Python 中 bool 是 int 的子类）。
            """
            if isinstance(cell, bool):
                if val.lower() in ("true", "1", "yes"):
                    return True
                if val.lower() in ("false", "0", "no"):
                    return False
                return None
            if isinstance(cell, int):
                try:
                    return int(val)
                except (ValueError, TypeError):
                    return None
            if isinstance(cell, float):
                try:
                    return float(val)
                except (ValueError, TypeError):
                    return None
            return cell

        def predicate(row_dict: dict) -> bool:
            cell = row_dict.get(target_col)
            if cell is None:
                return False
            if is_contains:
                return target_val.lower() in str(cell).lower()
            typed_val = _coerce(target_val, cell)
            if typed_val is None:
                return False
            return cell == typed_val

        result_sd = filter(ctx.sheet_data, predicate)
        return PanelResult(sheet_data=result_sd, message=f"匹配 {len(result_sd.rows)} 行")

    def _execute_directory(self, ctx: PanelContext) -> PanelResult:
        directory = self._dir_edit.text().strip() or (ctx.directory or "")
        if not directory:
            return PanelResult(error="请选择或输入搜索目录")
        if not Path(directory).is_dir():
            return PanelResult(error="目录不存在")
        conditions = self._collect_dir_conditions()
        if not conditions:
            return PanelResult(error="请至少添加一个搜索条件")

        try:
            sd = search_files(directory, conditions)
        except Exception as exc:
            return PanelResult(error=str(exc))
        return PanelResult(sheet_data=sd, message=f"匹配 {len(sd.rows)} 行")

    def _collect_dir_conditions(self) -> list[tuple[str, object, str]]:
        conditions: list[tuple[str, object, str]] = []
        for row in self._dir_rows:
            hbox = row.layout()
            if hbox is None:
                continue
            col = hbox.itemAt(0)
            val = hbox.itemAt(1)
            mode = hbox.itemAt(2)
            if not col or not val or not mode:
                continue
            conditions.append((
                col.widget().currentText(),
                val.widget().text(),
                "contains" if mode.widget().currentIndex() == 1 else "exact",
            ))
        return conditions

    @property
    def status_label(self) -> QLabel:
        return self._status_label
