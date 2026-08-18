## 1. 包骨架与依赖

- [x] 1.1 在 `excelOps/pyproject.toml` 中添加 `gui` optional-dependencies：`pyside6>=6.6,<6.7`
- [x] 1.2 更新 `[tool.setuptools.packages.find]` 的 `include` 字段，包含 `excelops*` 包
- [x] 1.3 创建 `excelOps/src/excelops_gui/__init__.py`
- [x] 1.4 创建 `excelOps/src/excelops_gui/__main__.py`：`python -m excelops_gui` 入口，检测 PySide6 可用性
- [x] 1.5 创建 `excelOps/tests/test_gui/conftest.py`：PySide6 `importorskip` autouse fixture

## 2. 核心基础设施

- [x] 2.1 创建 `excelops_gui/models/paginated_model.py`：`PaginatedModel(QAbstractTableModel)`
  - [x] 2.1.1 `rowCount()` 返回当前页行数（≤DEFAULT_PAGE_SIZE）
  - [x] 2.1.2 `data()` 从 `SheetData.rows[start:start+page_size]` 切片
  - [x] 2.1.3 `set_data(sd: SheetData)` 设置数据源，重置当前页
  - [x] 2.1.4 `next_page()` / `prev_page()` / `total_pages` 属性
- [x] 2.2 创建 `excelops_gui/panels/base.py`：`PanelContext` / `PanelResult` dataclass + `BasePanel` ABC
- [x] 2.3 创建 `excelops_gui/panels/registry.py`：`@register_panel` 装饰器 + `get_panel(name)`
- [x] 2.4 创建 `excelops_gui/workers/base.py`：`Worker(QObject)` 基类，定义 `progress` / `result` / `error` signal

## 3. 导航区

- [x] 3.1 创建 `excelops_gui/navigation.py`：文件/Sheet 树形导航
  - [x] 3.1.1 打开文件对话框（`QFileDialog.getOpenFileName`，过滤 `*.xlsx`）
  - [x] 3.1.2 调用 `list_sheets()` 获取 sheet 列表
  - [x] 3.1.3 树节点选中 → signal 发出 `(file_path, sheet_name)`

## 4. 数据区

- [x] 4.1 创建 `excelops_gui/data/data_table.py`：`QTableView` + 分页控件 + 状态标签
  - [x] 4.1.1 分页控件：`[首页][上一页] X/Y [下一页][末页] 共 N 行`
  - [x] 4.1.2 空数据提示："无数据"
  - [x] 4.1.3 连接 `PaginatedModel` 与分页按钮
- [x] 4.2 创建 `excelops_gui/data/delegate.py`：单元格渲染代理（日期/数字格式）

## 5. 搜索面板

- [x] 5.1 创建 `excelops_gui/panels/search.py`：`SearchPanel(BasePanel)`
  - [x] 5.1.1 单文件模式 UI：列下拉 + 值输入 + 模式选择（精确/模糊）+ 搜索按钮
  - [x] 5.1.2 目录模式 UI：目录选择 + 条件行列表（可添加/删除）+ 搜索按钮
  - [x] 5.1.3 模式切换：单选按钮（当前 sheet / 目录扫描）
  - [x] 5.1.4 `execute(ctx)`：单文件模式 → `read_sheet()` + `ops.filter()`；目录模式 → `search_files()`
- [x] 5.2 创建搜索 Worker：后台执行 `SearchPanel.execute()`，signal 返回 `PanelResult`

## 6. MainWindow 组装

- [x] 6.1 创建 `excelops_gui/main_window.py`：`QMainWindow`
  - [x] 6.1.1 `QSplitter` 三区布局
  - [x] 6.1.2 顶部工具栏：打开文件/目录、导出按钮、状态标签
  - [x] 6.1.3 操作面板切换器（Tab，当前只有搜索）
  - [x] 6.1.4 信号连接：导航选中 → 加载数据 → 更新 `PaginatedModel`
  - [x] 6.1.5 信号连接：搜索完成 → 更新 `PaginatedModel`

## 7. 导出

- [x] 7.1 创建 `excelops_gui/exporter.py`：`export_to_xlsx(sd: SheetData, path: Path)`
  - [x] 7.1.1 `QFileDialog.getSaveFileName`，默认 `.xlsx`
  - [x] 7.1.2 后台线程执行 `write_workbook()`
  - [x] 7.1.3 完成/错误 signal

## 8. 主题

- [x] 8.1 创建 `excelops_gui/theme/light.qss`：浅色简洁风样式表
  - [x] 8.1.1 色板：白底 #FFFFFF、浅灰 #F5F5F5、细边框 #E0E0E0、主色 #1A73E8
  - [x] 8.1.2 控件样式：按钮、表格、树形控件、标签
- [x] 8.2 在 `__main__.py` 中加载并应用 QSS

## 9. 测试

- [x] 9.1 编写 `excelOps/tests/test_gui/test_paginated_model.py`
  - [x] 9.1.1 数据超过一页时分页正确
  - [x] 9.1.2 翻页数据正确
  - [x] 9.1.3 数据少于一页
  - [x] 9.1.4 空数据
- [x] 9.2 编写 `excelOps/tests/test_gui/test_search_panel.py`
  - [x] 9.2.1 单文件模式调用 `read_sheet()` + `ops.filter()`
  - [x] 9.2.2 目录模式调用 `search_files()`
  - [x] 9.2.3 错误处理（无打开文件）
- [x] 9.3 编写 `excelOps/tests/test_gui/test_main_window.py`
  - [x] 9.3.1 MainWindow 初始化三区布局
  - [x] 9.3.2 打开文件 → 数据加载
- [x] 9.4 编写 `excelOps/tests/test_gui/test_exporter.py`
  - [x] 9.4.1 导出 SheetData → xlsx 文件存在且可读取

## 10. 验证

- [x] 10.1 `cd excelOps && pytest tests/test_gui/ -q` 全部通过（28 passed）
- [x] 10.2 `cd excelOps && pytest tests/ -q` 确保无回归（229 passed）
- [x] 10.3 `cd excelOps && ruff check src/excelops_gui/` 零 error
- [ ] 10.4 `pip install -e '.[gui]'` 安装成功
- [ ] 10.5 `python -m excelops_gui` 启动成功（有 GUI 环境时）