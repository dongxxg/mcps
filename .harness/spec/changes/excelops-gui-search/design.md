## Why

excelOps 已有完整的 library API（`read_sheet` / `search_files` / `ops.filter` / `write_workbook`），但只有编程调用方式。用户需要无需写代码的桌面搜索工具。

## What Changes

- **新增 `excelops_gui` 包**（PySide6 桌面客户端），三区布局 MainWindow，首期实现搜索功能
- **操作面板可插拔架构**：注册表模式，搜索是第一个面板
- **PaginatedModel**：QAbstractTableModel + 500 行/页分页
- **后台线程搜索**：QThread Worker + Signal/Slot
- **一键导出**：搜索结果 → 新 xlsx
- **浅色简洁风主题**：QSS 样式表

**BREAKING**：无。`excelops` library 零改动，纯新增 GUI 包。

## Capabilities

### New Capabilities

- `gui-search`：桌面客户端搜索功能（单文件浏览搜索 + 目录跨文件搜索）。

### Modified Capabilities

- 无。

## Impact

- **代码**：新增 `excelOps/src/excelops_gui/` 包（~10 个模块），更新 `excelOps/pyproject.toml`。
- **依赖**：新增 `pyside6>=6.6,<6.7`（仅 `gui` extra）。
- **测试**：新增 `excelOps/tests/test_gui/`。
- **兼容性**：完全向后兼容，`pip install excelops` 行为不变。