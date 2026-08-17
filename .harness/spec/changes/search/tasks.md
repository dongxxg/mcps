## 1. 错误类型

- [ ] 1.1 在 `excelops/errors.py` 新增 `SearchError(ExcelOpsError)` 子类
- [ ] 1.2 更新 `excelops/__init__.py` 导出 `SearchError`

## 2. 搜索模块实现

- [ ] 2.1 实现 `excelops/search.py`：
  - [ ] 2.1.1 `search_files(directory, conditions) → SheetData` — 公共入口
  - [ ] 2.1.2 `_glob_xlsx(directory) → list[Path]` — glob 目录下 .xlsx 文件（不递归）
  - [ ] 2.1.3 `_scan_file(path) → list[tuple[str, SheetData]]` — 读取一个文件的所有 sheet
  - [ ] 2.1.4 `_match_rows(data, conditions) → list[MatchInfo]` — 纯函数核心匹配逻辑
  - [ ] 2.1.5 `_build_result_column_order(all_data) → tuple[str, ...]` — 列名并集排序
  - [ ] 2.1.6 `_assemble_rows(hits, column_order) → list[tuple]` — 组装结果行（附加列 + 并集列）
  - [ ] 2.1.7 内部 `MatchInfo` 命名元组/数据类（row, columns, file, sheet, match_field, priority）

## 3. 导出

- [ ] 3.1 更新 `excelops/__init__.py` 导出 `search_files`

## 4. 测试

- [ ] 4.1 编写 `excelOps/tests/test_search.py`：
  - [ ] 4.1.1 精确匹配命中（编码 / 条码 / 名称各级优先级）
  - [ ] 4.1.2 高优先级未命中→低优先级命中
  - [ ] 4.1.3 所有条件均未命中→不出现
  - [ ] 4.1.4 类型保真：int vs str 不匹配，int vs float 匹配
  - [ ] 4.1.5 该表无目标列→跳过
  - [ ] 4.1.6 多 sheet 命中
  - [ ] 4.1.7 空 sheet 跳过
  - [ ] 4.1.8 返回数据含来源列（__file__/__sheet__/__match_field__/__priority__）
  - [ ] 4.1.9 多文件列名并集 + None 填充
  - [ ] 4.1.10 结果按 priority 升序 + file 字典序
  - [ ] 4.1.11 无匹配返回空 SheetData
  - [ ] 4.1.12 目录不存在抛 SearchError
  - [ ] 4.1.13 目录无 xlsx 抛 SearchError
  - [ ] 4.1.14 conditions 为空抛 SearchError
  - [ ] 4.1.15 _match_rows() 纯函数单独测试

## 5. 验证

- [ ] 5.1 `pytest excelOps/tests/test_search.py -v` 全部通过
- [ ] 5.2 `ruff check excelOps/src/excelops/search.py` 零 error
- [ ] 5.3 `pytest excelOps/tests/ -q` 确保无回归