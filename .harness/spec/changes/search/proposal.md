## Why

excelOps 已有的 `lookup` 原语解决的是**单表内**行对行映射：给定一张源表和一张参照表，按优先级键查找后带回列。但实际业务中，用户经常面对的是**一批 Excel 价格表**（可能分区域、分渠道、分时间），需要根据一个编码（如身份证式编码）找出它出现在哪些表的哪一行，取不到再退而求其次用条码或名称匹配。

当前要完成这个需求，用户必须自己写"扫目录 → 读每个文件 → 读每个 sheet → 逐行匹配 → 合并结果"的胶水代码，重复、易错、且无法复用。本次变更将这一模式沉淀为 excelOps 的标准能力。

## What Changes

- **新增 `excelops/search.py` 模块**：提供跨文件搜索的公共入口 `search_files()`，以及可单独测试的纯函数 `_match_rows()`。
- **新增 `SearchError(ExcelOpsError)` 错误类型**：挂入现有异常树，与 `ReadError` / `LookupError` 同层级。
- **扩展 `excelops/__init__.py`**：导出 `search_files` 和 `SearchError`。
- **新增测试**：`tests/test_search.py`，覆盖匹配逻辑、多文件列并集、排序、错误路径。

**BREAKING**：无。纯新增，不修改任何已有接口。

## Capabilities

### New Capabilities

- `search-files`：给定一个目录和优先级有序的字段-值条件列表，扫描目录内所有 `.xlsx` 文件的所有 sheet，返回按优先级排序的匹配行及其来源信息。

### Modified Capabilities

- 无。

## Impact

- **代码**：新增 `excelops/src/excelops/search.py`（~150 行），扩展 `excelops/errors.py`，扩展 `excelops/__init__.py`。
- **依赖**：仅依赖现有 `backends.reader` 和标准库，**不引入新依赖**，**不依赖 `[duckdb]`**。
- **测试**：新增 `excelOps/tests/test_search.py`。
- **兼容性**：完全向后兼容。