"""TDD RED tests for SearchPanel execution paths (headless, no dialog)."""

from __future__ import annotations

from excelops.backends.models import SheetData
from excelops_gui.panels.base import PanelContext, PanelResult
from excelops_gui.panels.search import SearchPanel


def test_no_open_file_returns_error(app) -> None:  # noqa: F811
    panel = SearchPanel()
    panel.set_columns(("编码",))
    panel._col_combo.setCurrentText("编码")
    ctx = PanelContext()
    result = panel.execute(ctx)
    assert isinstance(result, PanelResult)
    assert result.error == "请先打开一个文件"


def test_single_file_exact_match(app, tmp_path) -> None:  # noqa: F811
    sd = SheetData(
        columns=("编码", "名称"),
        rows=(("A001", "牛奶"), ("A002", "面包"), ("A003", "牛奶饮品")),
    )
    panel = SearchPanel()
    panel.set_columns(sd.columns)
    panel.set_active_sheet(str(tmp_path / "x.xlsx"), "s1")
    panel._col_combo.setCurrentText("编码")
    panel._value_input.setText("A001")
    panel._mode_combo.setCurrentIndex(0)  # exact
    panel._rd_single.setChecked(True)

    ctx = PanelContext(
        file_path=str(tmp_path / "x.xlsx"),
        sheet_name="s1",
        sheet_data=sd,
    )
    result = panel.execute(ctx)
    assert result.error is None
    assert result.sheet_data is not None
    assert len(result.sheet_data.rows) == 1
    assert result.message == "匹配 1 行"


def test_single_file_contains_match(app, tmp_path) -> None:  # noqa: F811
    sd = SheetData(
        columns=("名称",),
        rows=(("牛奶",), ("面包",), ("牛奶饮品",)),
    )
    panel = SearchPanel()
    panel.set_columns(sd.columns)
    panel.set_active_sheet(str(tmp_path / "x.xlsx"), "s1")
    panel._col_combo.setCurrentText("名称")
    panel._value_input.setText("牛奶")
    panel._mode_combo.setCurrentIndex(1)  # contains
    panel._rd_single.setChecked(True)

    ctx = PanelContext(file_path=str(tmp_path / "x.xlsx"), sheet_name="s1", sheet_data=sd)
    result = panel.execute(ctx)
    assert result.error is None
    assert result.sheet_data is not None
    assert len(result.sheet_data.rows) == 2


def test_no_sheet_data_returns_error(app) -> None:  # noqa: F811
    panel = SearchPanel()
    panel.set_columns(("编码",))
    panel.set_active_sheet("x.xlsx", "s1")
    panel._col_combo.setCurrentText("编码")
    panel._rd_single.setChecked(True)
    ctx = PanelContext(file_path="x.xlsx", sheet_name="s1", sheet_data=None)
    result = panel.execute(ctx)
    assert result.error == "当前 sheet 数据不可用"


def test_directory_missing_returns_error(app, tmp_path) -> None:  # noqa: F811
    panel = SearchPanel()
    panel._rd_dir.setChecked(True)
    panel._dir_edit.setText(str(tmp_path / "nope"))
    panel.execute(PanelContext())
    ctx = PanelContext(directory=str(tmp_path / "nope"))
    result = panel.execute(ctx)
    assert result.error == "目录不存在"


def test_directory_no_conditions_returns_error(app, tmp_path) -> None:  # noqa: F811
    panel = SearchPanel()
    panel._rd_dir.setChecked(True)
    panel._dir_edit.setText(str(tmp_path))
    ctx = PanelContext(directory=str(tmp_path))
    result = panel.execute(ctx)
    assert result.error == "请至少添加一个搜索条件"
