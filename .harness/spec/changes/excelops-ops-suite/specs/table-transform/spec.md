## ADDED Requirements

### Requirement: 字段映射
系统 SHALL 支持将源表的列映射到目标列（source_col → target_col），作为转换的基本操作。

#### Scenario: 单列映射
- **WHEN** 规则 `{"source": "product_name", "target": "商品名称"}`
- **THEN** 目标表列 "商品名称" 的值等于源表 "product_name" 的值

#### Scenario: 多列映射
- **WHEN** 规则列表含 3 条字段映射
- **THEN** 目标表包含 3 个映射后的列

### Requirement: 计算公式
系统 SHALL 支持通过公式派生目标列的值（引用其他列名进行算术运算）。

#### Scenario: 算术公式
- **WHEN** 规则 `{"target": "采购量", "expr": "安全库存 - 当前库存 + 预计销量"}`
- **THEN** 目标表 "采购量" 等于该行 "安全库存" - "当前库存" + "预计销量"

#### Scenario: 公式引用不存在的列
- **WHEN** 公式引用了源表中不存在的列
- **THEN** 系统抛出 `TransformError`，消息指明缺失的列名

### Requirement: 单位换算
系统 SHALL 支持对列值乘以换算系数（如箱→瓶：×12）。

#### Scenario: 乘以系数
- **WHEN** 规则 `{"source": "箱数", "target": "瓶数", "factor": 12}`
- **THEN** 目标表 "瓶数" = 源表 "箱数" × 12

### Requirement: 条件分支
系统 SHALL 支持按条件决定目标列的值（if-then-else 语义）。

#### Scenario: 单条件分支
- **WHEN** 规则 `{"target": "是否补货", "condition": "当前库存 < 安全库存", "then": "是", "else": "否"}`
- **THEN** 满足条件的行 "是否补货"="否"...（按实际逻辑填充）

### Requirement: 聚合
系统 SHALL 支持按指定列分组后对其他列做聚合（sum/avg/count/max/min）。

#### Scenario: 按仓库汇总采购量
- **WHEN** 规则 `{"group_by": "仓库", "aggregations": {"采购量": "sum"}}`
- **THEN** 输出表按 "仓库" 分组，每组的 "采购量" 为组内求和

### Requirement: 规则顺序执行
系统 SHALL 按规则列表的顺序依次应用，后续规则可引用前面规则的输出列。

#### Scenario: 规则链
- **WHEN** 规则 1 派生 "采购量"，规则 2 的条件引用 "采购量"
- **THEN** 规则 2 能正确使用规则 1 派生的值

### Requirement: 多输入表支持
系统 SHALL 支持从多个输入表取列（通过表别名引用），用于需要跨表字段的场景。

#### Scenario: 从两张表取字段
- **WHEN** 输入 [库存表, 销售表]，规则引用 "库存表.当前库存" 和 "销售表.预计销量"
- **THEN** 目标表包含来自两张表的字段

### Requirement: 输入数据不变
系统 SHALL 永不修改输入的 `SheetData` 对象。

#### Scenario: 转换后原表不变
- **WHEN** 对表 A 和表 B 执行 transform，再读取表 A 的 rows
- **THEN** 表 A 的 rows 与操作前完全一致
