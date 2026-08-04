## 1. 基础设施

- [x] 1.1 在 `errors.py` 新增 `MergeError(ExcelOpsError)` 异常类
- [x] 1.2 在 `backends/models.py` 新增 `MergeResult(path, bytes_written, rows_written, sheets)` frozen dataclass
- [x] 1.3 在 `__init__.py` 导出 `merge_workbook`、`MergeResult`、`MergeError`

## 2. 核心合并引擎

- [x] 2.1 创建 `backends/merger.py`：实现 `_read_header_row(ws)` 提取 file_a Sheet 的表头（含合并单元格回填）
- [x] 2.2 实现 `_align_columns(a_cols, b_cols)`：union 列对齐，返回 `(merged_cols, a_mapping, b_mapping)`
- [x] 2.3 实现行重映射 + 样式继承写入逻辑（`_remap_row` / `_write_row_with_style` / `_copy_cell_style`）
- [x] 2.4 实现公开函数 `merge_workbook(path_a, path_b, out_path) -> MergeResult`：主流程 orchestrator（加载 file_a → 读 file_b → 逐 Sheet 合并 → save）

## 3. 错误处理

- [x] 3.1 `merge_workbook` 对 `path_a` 不存在 / 非 xlsx 抛出 `MergeError`
- [x] 3.2 对 `out_path` 父目录不存在抛出 `MergeError`
- [x] 3.3 对 `path_b` 不存在 / 非 xlsx 抛出 `MergeError`

## 4. 测试

- [x] 4.1 `tests/test_merger.py`：两个单 Sheet 文件成功合并（数据行数 = a + b）
- [x] 4.2 多 Sheet 按名称配对（双方都有 / 单方有的 Sheet）
- [x] 4.3 Union 列对齐：file_b 多列、file_a 多列、列顺序不同、列完全相同
- [x] 4.4 不去重：重复行保留
- [x] 4.5 格式保留：列宽、单元格样式（字体/颜色）、合并单元格
- [x] 4.6 类型保真：date / None / float / str 读回一致
- [x] 4.7 源文件不被修改：合并前后 file_a / file_b 字节一致
- [x] 4.8 错误处理：文件不存在、非 xlsx、输出目录不存在
- [x] 4.9 返回值验证：MergeResult 字段正确

## 5. 质量门禁

- [x] 5.1 `ruff check src/ tests/` 零 error
- [x] 5.2 测试覆盖：18 个 merger 测试全通过
- [x] 5.3 全量测试通过（95 passed）
