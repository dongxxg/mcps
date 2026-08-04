## Why

excelOps 当前只有**读取 → 分析 → 写出**的线性管道，缺少**文件间组合**能力。用户需要将两个结构相同（标题、视觉格式一致）的 Excel 纵向拼接为一个文件，同时完整保留列宽、颜色、合并单元格等视觉格式。这是 Excel ETL 的高频场景（如月度报表合并、多部门数据汇总），现有工具链无法覆盖。

## What Changes

- **新增** `excelops/backends/merger.py`：openpyxl 读写引擎驱动的合并模块
- **新增** `merge_workbook(path_a, path_b, out_path, ...) -> MergeResult` 公开函数
- **新增** `MergeError(ExcelOpsError)`：合并专用异常类型
- **扩展** `__init__.py`：导出 `merge_workbook`、`MergeResult`、`MergeError`
- **不修改**现有 reader / writer / analyzer / models（保持架构纯净）

## Capabilities

### New Capabilities

- `excel-merge`: 将两个标题和视觉格式相同的 xlsx 文件合并为一个全新 xlsx，按 Sheet 名配对、union 列对齐（缺失填 None）、不去重、完整保留 file_a 的视觉格式（列宽 / 单元格样式 / 合并单元格 / 行高）

### Modified Capabilities

（无）

## Impact

| 方面 | 影响 |
|------|------|
| 代码 | 新增 `backends/merger.py`（~150 行），扩展 `errors.py`、`__init__.py` |
| 公开 API | 新增 `merge_workbook`、`MergeResult`、`MergeError` |
| 依赖 | 仅使用已有核心依赖 openpyxl，无新增 |
| 现有功能 | 零影响——不修改任何现有模块 |
| 测试 | 新增 `tests/test_merger.py`（正常 + 边界 + 格式保留验证） |
| 架构权衡 | 合并写路径放弃 CoW 原子写（openpyxl 直写全新文件，源文件不受影响） |
