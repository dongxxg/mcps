## 1. 包脚手架与依赖

- [x] 1.1 创建 `excelOps/pyproject.toml`：src-layout，`name=excelops`，`requires-python=">=3.12"`；核心依赖 `openpyxl`+`xlsxwriter`；可选 extra `[duckdb]`=`duckdb`+`pyarrow`；`[dev]`=`pytest`+`ruff`（参照 serverOps 的 extras + ruff 配置）。本阶段**不设** `[project.scripts]` server 入口。
- [x] 1.2 创建 `excelOps/src/excelops/__init__.py`：作为 read/analyze/write 公开 API 导出点；`import excelops` SHALL NOT 因 duckdb 缺失而失败。
- [x] 1.3 创建 `excelOps/src/excelops/backends/__init__.py`（空占位，标注 policy-unaware）。
- [x] 1.4 建 venv 并验证 `pip install -e excelOps`（核心）与 `pip install -e 'excelOps[duckdb]'` 均成功。

## 2. 异常层级与数据模型（D7 / D2 / D9 / D10）

- [x] 2.1 实现 `errors.py`：`ExcelOpsError` 基类 + 子类 `ReadError`/`WriteError`/`AnalyzeError`/`UnsupportedFormat`/`FileLocked`/`MissingDependency`/`SafetyError`（占位，Phase 1 不抛但先占名与 import 路径）——参照 serverOps 的扁平异常树。
- [x] 2.2 实现 `backends/models.py`：`SheetData(columns: tuple[str,...], rows: tuple[tuple,...])` 冻结 dataclass + `SheetMeta(max_row, max_col)` + `WriteResult(path, bytes_written, rows_written, source_ref)`。

## 3. Reader（D4 / D10，对应 `excel-read` 规格）

- [x] 3.1 `list_sheets(path)`：openpyxl `read_only=True` 加载，返回有序表名；文件不存在 → `ReadError`；非 xlsx/损坏 → `UnsupportedFormat`。
- [x] 3.2 `read_sheet(path, sheet, header=True, data_only=True)`：流式读 → `SheetData`；缺尾 cell **pad 到 `len(columns)`**；表头**归一化**（None/重名 → 合法唯一占位）；混合类型保真（日期保持日期、不做隐式 str 化）；表不存在 → `ReadError`（信息列实际表名）。
- [x] 3.3 `sheet_meta(path, sheet)`：返回 `SheetMeta(max_row, max_col)`。

## 4. Analyzer（D3 / D6，对应 `excel-analyze` 规格）

- [x] 4.1 `Analyzer` 上下文管理器：`__enter__` 惰性 import duckdb（缺失 → `MissingDependency` + 安装提示 `pip install 'excelops[duckdb]'`），建连接（config 选内存库/文件库，默认内存库）；`__exit__` 关闭；退出后 `query` → `AnalyzeError`。
- [x] 4.2 `register(name, sheet_data)`：SheetData → pyarrow Table → `duckdb.register`；同名替换（CREATE OR REPLACE 语义）；不做隐式类型转换。
- [x] 4.3 `query(sql, params=None)`：命名参数 `:name` 绑定；结果 → `SheetData`；日期类型保真；无效 SQL → `AnalyzeError`。
- [x] 4.4 锁定公开面仅 `register`/`query`/`close`（+ 上下文协议），**不暴露** conn/cursor。

## 5. Writer（D5 / D9，对应 `excel-write` 规格）

- [x] 5.1 `write_workbook(path, sheets: dict[str, SheetData])`：xlsxwriter 写多表新工作簿；空 rows → 写表头-only 表；空 columns 且空 rows → `WriteError`；不可写路径/无效 SheetData → `WriteError`。
- [x] 5.2 实现 **Copy-on-Write 五步**：`tempfile.mkstemp(dir=target.parent)` → `os.fdopen` 写 → `flush`+`os.fsync`+`close` → `os.replace`（短重试 1-2 次，100-200ms 退避）→ 失败路径 `os.unlink(.tmp)` → 成功返回 `WriteResult`。
- [x] 5.3 目标被占用（`PermissionError`/WinError 5）→ 重试后 `FileLocked` + 清理 `.tmp`；SHALL NOT 抛裸 `PermissionError`。
- [x] 5.4 验证 SHALL NOT 就地修改传入 SheetData。

## 6. 验收测试（硬指标 5，对应全部规格的 scenario）

- [x] 6.1 **闭环测试**：`read_sheet(sample.xlsx,"orders")` → `Analyzer.register`+`query`（SQL 聚合）→ `write_workbook(result.xlsx)` → 重读校验列名与内容一致。
- [x] 6.2 **类型保真测试**：fixture `sample_mixed_types.xlsx`（日期列/空值列/浮点列/文本列），read→write→重读后**逐列类型断言**（datetime 仍为 datetime，非 ISO 字符串/序列号）。
- [x] 6.3 **大文件流式冒烟**：conftest 按需生成 10 万行+ 多表 fixture，断言跑完且不 OOM（内存上界或 wall time 合理）。
- [x] 6.4 **错误路径测试**：文件不存在→`ReadError`；损坏/非 xlsx→`UnsupportedFormat`；表不存在→`ReadError`；父目录不存在→`WriteError`；目标占用→`FileLocked`（mock `os.replace` 抛 `PermissionError`）；SQL 语法错→`AnalyzeError`；duckdb 未装→`MissingDependency`。
- [x] 6.5 **CoW 可观测测试**：注入写失败 → 既有 target 内容不变 + 无 `.tmp` 残留；成功 → target 正确 + 无残留 + `WriteResult` 字段完整。
- [x] 6.6 `ruff check` + `pytest` 全绿；CI 矩阵 3.12/3.13（3.14 上 `[duckdb]` 测试单独标记允许）。
