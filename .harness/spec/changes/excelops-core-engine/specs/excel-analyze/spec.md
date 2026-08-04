## ADDED Requirements

### Requirement: 将 SheetData 注册为可查询表

Analyzer SHALL 支持把一个 SheetData 注册为以指定名称可查询的表。注册 SHALL 在不依赖 pandas 的前提下完成（经 pyarrow Table 零拷贝，pyarrow 随 `[duckdb]` extra 安装）。对同名表的重复注册 SHALL 以替换语义生效（CREATE OR REPLACE），不抛错。Analyzer SHALL NOT 对注册的数据做隐式类型转换。

#### Scenario: 注册后可查询

- **WHEN** 将一个 3 列、N 行的 SheetData 以名 `orders` 注册后执行 `SELECT count(*) FROM orders`
- **THEN** 返回结果行数为 N

#### Scenario: 同名注册替换

- **WHEN** 先以 `orders` 注册 SheetData A，再以同名注册 SheetData B，随后查询
- **THEN** 查询结果反映 SheetData B 的内容

### Requirement: 参数化 SQL

query SHALL 支持命名参数（`:name` 占位符），参数经绑定传入，SHALL NOT 通过字符串拼接构造 SQL。

#### Scenario: 命名参数过滤

- **WHEN** 执行 `SELECT * FROM t WHERE region = :r`，参数 `{"r": "east"}`
- **THEN** 仅返回 region 为 east 的行

### Requirement: 查询结果回 SheetData

query 的结果 SHALL 以 SheetData 返回，其 `columns` 为 SELECT 列，`rows` 为结果行。

#### Scenario: 结果形状

- **WHEN** 执行 `SELECT region, sum(amount) AS total FROM t GROUP BY region`
- **THEN** 返回 SheetData，`columns == ["region", "total"]`，`rows` 为每组一行

### Requirement: 分析过程类型保真

经分析流转的类型 SHALL 保持稳定：日期列在注册→查询→结果中保持为日期类型，不退化为字符串或 Excel 序列号。

#### Scenario: 日期列往返

- **WHEN** 注册含 `created_at` 日期列的 SheetData，执行 `SELECT created_at FROM t`
- **THEN** 结果 SheetData 中该列单元格仍为日期类型

### Requirement: 会话级生命周期

Analyzer SHALL 实现为上下文管理器：进入时建立 DuckDB 连接（惰性导入 `duckdb`），退出时关闭。构造函数 SHALL 支持选择内存库或文件库（Phase 1 默认内存库）。退出后再次调用 query SHALL 抛出 `AnalyzeError`。

#### Scenario: 退出后不可用

- **WHEN** 在 `with Analyzer() as az:` 块退出后调用 `az.query(...)`
- **THEN** 抛出 `AnalyzeError`，提示会话已关闭

### Requirement: 连接不外泄

Analyzer 的公开接口 SHALL 仅暴露 `register`、`query`、`close`（及上下文管理协议方法），SHALL NOT 暴露底层 DuckDB 连接或游标对象。

#### Scenario: 公开面受限

- **WHEN** 检查一个 Analyzer 实例的公开属性与方法
- **THEN** 不存在可被外部直接操作 DuckDB 连接的属性

### Requirement: DuckDB 缺失的友好错误

当 `[duckdb]` extra 未安装时，Analyzer 的首次使用（进入会话）SHALL 抛出 `MissingDependency`，信息中给出安装提示（`pip install 'excelops[duckdb]'`）。`import excelops` 包本身 SHALL NOT 因 duckdb 缺失而失败。

#### Scenario: 未装 duckdb

- **WHEN** 在未安装 duckdb 的环境中进入 `Analyzer()` 会话
- **THEN** 抛出 `MissingDependency`，信息含安装提示；且 `import excelops` 不报错

### Requirement: SQL 错误的类型化异常

无效 SQL SHALL 抛出 `AnalyzeError`，包裹底层 DuckDB 错误信息，SHALL NOT 透传裸 DuckDB 异常。

#### Scenario: 语法错误

- **WHEN** 执行 `SELECT FROMM t`（语法错误）
- **THEN** 抛出 `AnalyzeError`
