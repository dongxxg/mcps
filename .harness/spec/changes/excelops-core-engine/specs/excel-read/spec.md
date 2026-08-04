## ADDED Requirements

### Requirement: 工作表枚举

系统 SHALL 提供列出 xlsx 工作簿内所有工作表名称的能力，返回顺序与工作簿内一致。

#### Scenario: 多表工作簿枚举

- **WHEN** 对一个包含 `[Sheet1, Summary, Data]` 三张表的工作簿调用工作表枚举
- **THEN** 返回 `["Sheet1", "Summary", "Data"]`，顺序与工作簿一致

#### Scenario: 不存在的文件

- **WHEN** 对一个不存在的路径调用工作表枚举
- **THEN** 抛出 `ReadError`（`ExcelOpsError` 子类），而非 openpyxl 原始异常

### Requirement: 工作表读取为 SheetData

系统 SHALL 提供将指定工作表读取为 `SheetData`（`columns: list[str]` + `rows: list[list]`）的能力。读取 SHALL 默认以首行为列名（`header=True`），并 SHALL 支持以 `header=False` 进行纯位置读取（列名退化为 `col_0, col_1, …`）。读取 SHALL 默认取单元格缓存值（`data_only=True`）。

#### Scenario: 带表头读取

- **WHEN** 以默认 `header=True` 读取一张首行为 `[region, amount]`、后续为数据行的工作表
- **THEN** 返回的 `SheetData.columns == ["region", "amount"]`，`rows` 为首行之外的数据行

#### Scenario: 无表头位置读取

- **WHEN** 以 `header=False` 读取同一工作表
- **THEN** `columns == ["col_0", "col_1"]`，`rows` 包含全部行（含原首行）

### Requirement: 大文件流式读取

读取 SHALL 基于 openpyxl `read_only=True` 模式实现，使内存占用与工作簿物理大小解耦（按行流式迭代），从而能够读取远超内存容量的大工作表。

#### Scenario: 大工作表不触发 OOM

- **WHEN** 读取一个含大量数据行（如 50 万行）的工作表
- **THEN** 读取成功完成，进程峰值内存不随行数线性膨胀

### Requirement: 工作表元信息

系统 SHALL 提供查询工作表元信息的能力，至少返回已用区域维度（最大行数、最大列数）。

#### Scenario: 获取维度

- **WHEN** 对一张数据填充到第 5 行、第 3 列的工作表查询元信息
- **THEN** 返回 `max_row == 5`、`max_col == 3`

### Requirement: 单元格值保真

读取 SHALL 保留单元格的原始值类型，不对数值、日期、布尔做有损强制转换。Reader SHALL NOT 对单元格做隐式字符串化。当 `read_only` 迭代产生参差不齐的行（缺尾 cell）时，reader SHALL 将每行 pad 到 `len(columns)` 以保证 `rows` 与 `columns` 对齐。

#### Scenario: 混合类型保真

- **WHEN** 读取一张同时含整数 `42`、日期 `2026-01-01`、文本 `"hello"` 的工作表
- **THEN** 对应单元格在 `rows` 中分别呈现为数值、日期对象、字符串

#### Scenario: 缺尾单元格对齐

- **WHEN** 读取一张末行仅前 2 列有值、但表共 4 列的工作表
- **THEN** 该行在 `rows` 中长度为 4，缺尾位置为 `None`

### Requirement: 表头归一化

当首行存在 `None` 或重复列名时，reader SHALL 进行归一化（合成唯一占位名，如 `col_0`、对重复名加序号），使 `columns` 始终为合法、唯一、非空的标识符序列，从而避免下游建表失败。

#### Scenario: 重复列名归一化

- **WHEN** 读取一张首行为 `[name, name, amount]` 的工作表
- **THEN** `columns` 为三个互不相同的合法标识符（如 `["name", "name_1", "amount"]`）

### Requirement: 缺失/损坏文件的类型化错误

当请求的工作表名不存在时，系统 SHALL 抛出 `ReadError`，错误信息须列出该工作簿实际拥有的工作表名。当文件不是合法 xlsx 或已损坏时，系统 SHALL 抛出 `UnsupportedFormat`。

#### Scenario: 请求不存在的表

- **WHEN** 对含 `[Sheet1, Sheet2]` 的工作簿请求读取 `Sheet3`
- **THEN** 抛出 `ReadError`，信息中包含 `Sheet1` 与 `Sheet2`

#### Scenario: 损坏的 xlsx

- **WHEN** 对一个内容为纯文本、并非 xlsx 格式的文件调用读取
- **THEN** 抛出 `UnsupportedFormat`
