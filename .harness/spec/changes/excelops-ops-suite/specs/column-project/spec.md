## ADDED Requirements

### Requirement: 按列名选取
系统 SHALL 按用户指定的列名列表从输入表中选取列，输出仅包含这些列。

#### Scenario: 选取部分列
- **WHEN** 输入表列 [a,b,c,d]，`columns=["b","d"]`
- **THEN** 输出表列 [b,d]，仅含这两列的数据

#### Scenario: 选取全部列（子集等于全集）
- **WHEN** 输入表列 [a,b,c]，`columns=["a","b","c"]`
- **THEN** 输出表列 [a,b,c]，数据完整

### Requirement: 列重命名映射
系统 SHALL 支持 `rename` 参数，将选取的列在输出中重命名。

#### Scenario: 部分列重命名
- **WHEN** `columns=["a","b"]`，`rename={"b":"B列"}`
- **THEN** 输出表列名为 ["a","B列"]

#### Scenario: 全部列重命名
- **WHEN** `columns=["a","b"]`，`rename={"a":"甲","b":"乙"}`
- **THEN** 输出表列名为 ["甲","乙"]

### Requirement: 输出列顺序
系统 SHALL 按 `columns` 列表的顺序排列输出列（用户控制顺序）。

#### Scenario: 逆序输出
- **WHEN** 输入表列 [a,b,c]，`columns=["c","a","b"]`
- **THEN** 输出表列顺序为 [c,a,b]

### Requirement: 列不存在时抛出错误
系统 SHALL 当 `columns` 中包含表中不存在的列时抛出 `ProjectError`。

#### Scenario: 列名不存在
- **WHEN** 输入表列 [a,b]，`columns=["a","not_exist"]`
- **THEN** 系统抛出 `ProjectError`，消息包含不存在的列名 "not_exist"

### Requirement: 不修改输入数据
系统 SHALL 永不修改输入的 `SheetData` 对象。

#### Scenario: 投影后原表不变
- **WHEN** 对表 A 执行 column-project，再读取表 A 的 columns
- **THEN** 表 A 的 columns 与操作前完全一致
