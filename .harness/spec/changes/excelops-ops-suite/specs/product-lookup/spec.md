## ADDED Requirements

### Requirement: 优先级多级匹配
系统 SHALL 按用户指定的键优先级顺序依次尝试匹配，高优先级键匹配成功则立即返回，不再尝试低优先级键。默认优先级为 编码 → 商品条码 → 商品名称。

#### Scenario: 编码匹配成功
- **WHEN** 源表某行编码为 "A001"，价格表编码列存在 "A001"
- **THEN** 该行通过编码匹配到价格表对应行，带回指定列

#### Scenario: 编码未匹配，条码匹配成功
- **WHEN** 源表某行编码为 "A001"（价格表无此编码），但条码 "6901234" 在价格表中存在
- **THEN** 该行通过条码匹配到价格表对应行

#### Scenario: 编码和条码均未匹配，名称匹配成功
- **WHEN** 源表某行编码和条码均未匹配，但商品名称 "纯牛奶 250ml" 在价格表中存在
- **THEN** 该行通过名称匹配到价格表对应行

#### Scenario: 三级均未匹配
- **WHEN** 源表某行的编码、条码、名称在价格表中均不存在
- **THEN** 根据 `on_missing` 配置处理（见未匹配处理需求）

### Requirement: 带回指定列
系统 SHALL 从匹配到的价格表行中，仅带回用户指定的列（`fetch_columns`），并以用户指定的前缀/别名附加到源表。

#### Scenario: 带回单列
- **WHEN** `fetch_columns=["单价"]`，匹配成功
- **THEN** 源表新增列 "单价"，值为价格表对应值

#### Scenario: 带回多列并指定别名
- **WHEN** `fetch_columns={"单价": "最新单价", "税率": "适用税率"}`，匹配成功
- **THEN** 源表新增列 "最新单价" 和 "适用税率"

### Requirement: 未匹配行的处理策略
系统 SHALL 支持配置 `on_missing` 策略，决定三级均未匹配时的行为。

#### Scenario: on_missing="mark"（默认）
- **WHEN** 某行三级均未匹配，`on_missing="mark"`（默认值）
- **THEN** 该行带回列的值均为 "__未找到__"，便于用户筛查

#### Scenario: on_missing="null"
- **WHEN** 某行三级均未匹配，`on_missing="null"`
- **THEN** 该行带回列的值均为 None

#### Scenario: on_missing="error"
- **WHEN** 某行三级均未匹配，`on_missing="error"`
- **THEN** 系统抛出 `LookupError`，消息包含该行的键值信息

### Requirement: 重复键处理
系统 SHALL 明确定义价格表中存在重复键时的行为。

#### Scenario: 价格表中某编码对应多行
- **WHEN** 价格表中编码 "A001" 对应 2 行（如不同批次）
- **THEN** 取第一匹配行（确定性行为），不抛错
