## ADDED Requirements

### Requirement: 多张表纵向堆叠
系统 SHALL 接受多个 `SheetData` 输入，按列名对齐后纵向堆叠（UNION ALL 语义）为一张表，不去重、不丢弃任何数据行。

#### Scenario: 格式一致的多表堆叠
- **WHEN** 输入 3 张列名完全相同的表（各有 10 行）
- **THEN** 输出一张表，列名不变，共 30 行数据

#### Scenario: 格式不一致但列名存在交集
- **WHEN** 输入表 A（列 [a,b,c]）和表 B（列 [b,c,d]），两者有交集列 b、c
- **THEN** 输出表列名为并集 [a,b,c,d]，A 的行在 d 列填 None，B 的行在 a 列填 None

#### Scenario: 输入表列名完全不同
- **WHEN** 输入表 A（列 [a,b]）和表 B（列 [c,d]），无交集列
- **THEN** 输出表列名为并集 [a,b,c,d]，所有行在对方列上填 None

### Requirement: 用户指定输出列顺序
系统 SHALL 接受 `column_order` 参数，按该列表指定的顺序排列输出列。

#### Scenario: 指定列顺序
- **WHEN** 输入表列 [a,b,c,d]，`column_order=["c","a","d"]`
- **THEN** 输出表列顺序为 [c,a,d]，不包含 b

#### Scenario: column_order 为空时以首表为基准
- **WHEN** 输入 3 张表，首表列 [x,y,z]，未传 column_order（或传 None）
- **THEN** 输出表列顺序以首表为基准，后续表的新列追加到末尾

#### Scenario: column_order 包含不存在列
- **WHEN** `column_order=["a","not_exist"]`，表中无 not_exist 列
- **THEN** 系统抛出 `CombineError`，消息指明不存在的列名

### Requirement: 空输入与单表输入
系统 SHALL 对空输入和单表输入有明确定义的行为。

#### Scenario: 空列表输入
- **WHEN** 输入空列表 `[]`
- **THEN** 系统抛出 `CombineError`，消息指明至少需要一张表

#### Scenario: 单表输入
- **WHEN** 输入仅一张表，`column_order=None`
- **THEN** 输出为该表的深等价副本（列顺序与行数据一致）

### Requirement: 不修改输入数据
系统 SHALL 永不修改输入的 `SheetData` 对象（保持不可变契约）。

#### Scenario: 合并后原表不变
- **WHEN** 输入表 A 后执行合并，再读取表 A 的 rows
- **THEN** 表 A 的 rows 与合并前完全一致
