## ADDED Requirements

### Requirement: 跨文件目录搜索

系统 SHALL 扫描给定目录下的所有 `.xlsx` 文件（**不递归**子目录），对每个文件的**所有工作表**执行字段值匹配。

#### Scenario: 目录包含多个 xlsx 文件
- **WHEN** 目录下有 `price_A.xlsx`、`price_B.xlsx`、`notes.txt`
- **THEN** 仅搜索 `price_A.xlsx` 和 `price_B.xlsx`，`notes.txt` 被忽略

#### Scenario: 目录下无 xlsx 文件
- **WHEN** 目录为空或不含 `.xlsx` 文件
- **THEN** 系统抛出 `SearchError`，消息指明目录内无 `.xlsx` 文件

#### Scenario: 目录不存在
- **WHEN** 传入的目录路径不存在
- **THEN** 系统抛出 `SearchError`，消息指明目录不存在

### Requirement: 优先级字段-值匹配

系统 SHALL 按 `conditions` 列表的顺序依次尝试匹配，第一个命中即停止（high-priority wins）。默认精确匹配（exact），不隐式类型转换。

#### Scenario: 高优先级字段命中
- **WHEN** `conditions=[("编码", "A001"), ("条码", "6901234")]`，某行编码="A001"
- **THEN** 该行通过"编码"字段命中，`__match_field__`="编码"，`__priority__`=0

#### Scenario: 高优先级未命中，低优先级命中
- **WHEN** `conditions=[("编码", "A001"), ("条码", "6901234")]`，某行编码="B002" 但条码="6901234"
- **THEN** 该行通过"条码"字段命中，`__match_field__`="条码"，`__priority__`=1

#### Scenario: 所有条件均未命中
- **WHEN** 某行的所有条件字段值均不匹配
- **THEN** 该行不出现在结果中（静默跳过，不报错）

#### Scenario: 精确匹配保持类型保真
- **WHEN** 条件值为数字 `123`，表中对应单元格为字符串 `"123"`
- **THEN** 不匹配（类型不同，`123 != "123"`）

#### Scenario: int 与 float 相等
- **WHEN** 条件值为 `123`（int），表中对应单元格为 `123.0`（float）
- **THEN** 匹配（Python 原生 `123 == 123.0` 为 True）

#### Scenario: 该表无目标列
- **WHEN** 条件包含"编码"字段，但某 sheet 的列中不含"编码"
- **THEN** 跳过"编码"条件的匹配尝试，继续尝试下一个条件；若所有条件列均不存在则跳过该 sheet

#### Scenario: 条件值为 None
- **WHEN** 条件值为 `None`，表中对应单元格也为 `None`
- **THEN** 匹配成功（`None == None`）

### Requirement: 全扫所有工作表

系统 SHALL 对每个 `.xlsx` 文件的**所有工作表**执行搜索，不跳过空表或非首表。

#### Scenario: 单文件多 sheet 命中
- **WHEN** `price_A.xlsx` 含 sheet1（无匹配）和 sheet2（有匹配）
- **THEN** sheet2 的匹配行出现在结果中，`__sheet__`="sheet2"

#### Scenario: 空 sheet
- **WHEN** 某 sheet 无数据行（仅有表头或完全为空）
- **THEN** 静默跳过，不报错

### Requirement: 返回数据包含来源信息

系统 SHALL 在返回的 `SheetData` 中附加以下列：

| 列名 | 类型 | 含义 |
|---|---|---|
| `__file__` | `str` | 来源文件名（basename，不含目录路径） |
| `__sheet__` | `str` | 来源工作表名 |
| `__match_field__` | `str` | 命中时使用的字段名 |
| `__priority__` | `int` | 命中时的优先级序号（0 = 最高优先级） |

#### Scenario: 结果包含来源列
- **WHEN** 搜索返回匹配行
- **THEN** 每行包含 `__file__`、`__sheet__`、`__match_field__`、`__priority__` 四列，值为对应来源信息

### Requirement: 多文件列名并集

系统 SHALL 将所有文件的原始列名取并集作为结果的数据列，不存在的列填 `None`。

#### Scenario: 列名一致的多个文件
- **WHEN** 文件 A 列 `[编码, 条码, 单价]`，文件 B 列 `[编码, 条码, 单价]`
- **THEN** 结果数据列为 `[编码, 条码, 单价]`

#### Scenario: 列名不一致的多个文件
- **WHEN** 文件 A 列 `[编码, 条码, 单价]`，文件 B 列 `[编码, 条码, 市场价]`
- **THEN** 结果数据列为 `[编码, 条码, 单价, 市场价]`（首文件列优先保序，新增列追加末尾），A 的行在"市场价"填 `None`，B 的行在"单价"填 `None`

#### Scenario: 列名完全不同
- **WHEN** 文件 A 列 `[编码, 名称]`，文件 B 列 `[sku, price]`
- **THEN** 结果数据列为 `[编码, 名称, sku, price]`，A 的行在 sku/price 填 `None`，B 的行在编码/名称填 `None`

### Requirement: 结果排序

系统 SHALL 按 `__priority__` 升序（高优先级在前）排序结果行；同级内按 `__file__` 字典序排序，保证确定性输出。

#### Scenario: 多级优先级混合结果
- **WHEN** 结果包含 priority=0 和 priority=1 的行
- **THEN** priority=0 的行排在 priority=1 之前

#### Scenario: 同级多文件结果
- **WHEN** 多个文件均以 priority=0 命中
- **THEN** 按 `__file__` 字典序排列

### Requirement: 无匹配结果

系统 SHALL 在没有任何匹配结果时返回一个**空 `SheetData`**（含附加列 + 并集列，0 行），不抛异常。

#### Scenario: 所有文件均无匹配
- **WHEN** 目录内所有文件的所有 sheet 均无匹配行
- **THEN** 返回 `SheetData(columns=(...), rows=())`，columns 包含附加列和列名并集

### Requirement: 参数校验

系统 SHALL 对非法参数抛出 `SearchError`。

#### Scenario: conditions 为空
- **WHEN** `conditions=[]`
- **THEN** 抛出 `SearchError`，消息指明 conditions 不能为空

#### Scenario: 条件字段名含非法字符
- **WHEN** 条件字段名为空字符串 `""` 或 `None`
- **THEN** 抛出 `SearchError`，消息指明字段名无效

### Requirement: 不修改输入

系统 SHALL 永不修改任何输入数据（保持不可变契约）。`search_files` 内部产生的所有 `SheetData` 均为新建对象。

#### Scenario: 搜索后源文件不变
- **WHEN** 执行搜索后再次读取原始 `.xlsx` 文件
- **THEN** 文件内容与搜索前一致