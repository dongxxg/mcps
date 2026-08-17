## Context

excelOps Phase 1 已交付 `read → analyze → write` 骨干，Phase 1.5 交付了 `ops/` 业务操作层（6 个原语 + 6 个配方）。用户需要一个新的能力：**跨文件目录搜索**——给定一个编码（或条码/名称），在一批价格表中找出它出现在哪些文件、哪些行。

已有 `ops/lookup` 解决单表内行对行映射，但**跨文件搜索是不同维度的需求**：输入是"一个值 + 目录"，输出是"匹配行 + 来源信息"。

**已知约束**：
- `SheetData` 不可变契约
- backends 保持 policy-unaware，search 模块同样不碰安全/审计
- 不引入新依赖，不强制 `[duckdb]`
- 匹配保持类型保真（D10），日期仍是 date，数字仍是 int/float，不隐式转字符串

## Goals / Non-Goals

**Goals:**
- 新增 `search.py` 模块，提供 `search_files()` 公共入口
- 两种匹配模式：`exact`（精确，类型保真）和 `contains`（子串，不区分大小写），支持全局默认 + 逐条件覆盖
- 全扫目录内所有 `.xlsx` 文件的所有 sheet
- 返回带来源信息的 `SheetData`（附加列 + 列名并集）
- 纯 Python 实现，不依赖 DuckDB

**Non-Goals:**
- 正则 / 编辑距离 / 模糊匹配（后续扩展）
- 一字段多值（后续扩展）
- CSV / XLS 格式支持（仅 xlsx）
- 结果导出到文件（纯内存返回）
- MCP 工具封装（Phase 2）
- 递归扫描子目录

## Decisions

### D1: 新增独立模块 `search.py`，不放入 ops/ 层

**选择**：在 `excelops/` 根目录下新增 `search.py`，与 `backends/` 和 `ops/` 同级。

**理由**：`ops/` 层的设计契约是"纯函数、零 I/O、消费 SheetData 返回 SheetData"。跨文件搜索的核心输入之一是**文件目录**（需要 glob 扫描、逐个 open 文件），这属于文件系统操作，必须位于 I/O 层。新增独立模块最符合 excelOps 的分层架构：

```
excelops/
├── backends/        # I/O 层（reader/analyzer/writer/merger）
├── ops/             # 纯函数业务操作层
├── search.py        # 新增：跨文件搜索（I/O + 匹配编排）
├── errors.py        # 错误类型
└── __init__.py      # 公共导出
```

search.py 的 I/O 部分调用 `backends.reader`，匹配逻辑可复用 `ops.filter` 的谓词模式。

**替代方案**：
- A) 放入 `ops/` 作为配方（recipe）—— **不采用**：违反 ops 层零 I/O 契约，且需要新增"有 I/O 的 recipe"先例，模糊层级边界。
- B) 放入 `backends/` —— **不采用**：backends 是底层引擎（openpyxl/DuckDB/xlsxwriter 封装），search 是业务能力编排，层级不匹配。

### D2: 返回 SheetData + 附加列，不新建 SearchHit 类型

**选择**：返回 `SheetData`，附加 4 列来源信息（`__file__` / `__sheet__` / `__match_field__` / `__priority__`），数据列为所有文件的列名并集。

**理由**：
1. `SheetData` 是 excelOps 的脊椎类型，所有 ops（`filter` / `derive` / `narrate`）只吃 `SheetData`。返回 SheetData 让调用方可以直接链式调用后续 ops，不需要学新类型。
2. 附加列用 `__` 前缀命名，与数据列命名空间隔离，避免与原始列名冲突。

**替代方案**：
- A) 新建 `SearchHit` 数据类（Architect 初始建议）—— **不采用**：引入新类型，调用方需要额外适配逻辑才能与 ops 层协作，且 `SearchHit` 无法被 `filter`/`derive`/`narrate` 直接消费。
- B) 返回 `list[SheetData]`（每文件一个）—— **不采用**：调用方需要手动合并，且无法统一排序。

### D3: 多文件列名并集策略

**选择**：取所有文件的原始列名并集作为结果的数据列，按"首文件列顺序 + 后续文件新增列追加"排列，缺失列填 `None`。

**理由**：
1. `SheetData` 要求统一的 `columns`，无法为不同文件返回不同列结构，并集是唯一可行方案。
2. "首文件列优先保序"让最常见的场景（多个文件列结构一致）零成本工作。
3. `None` 填充语义清晰：该行没有该列的数据。

**替代方案**：
- A) 仅保留首文件的列结构，丢弃其他文件独有的列 —— **不采用**：信息丢失，调用方无法获取完整匹配数据。
- B) 仅保留所有文件都有的交集列 —— **不采用**：过度保守，列名稍有差异就丢大量数据。

### D4: 两种匹配模式 — exact + contains

**选择**：支持两种匹配模式：
- `exact`：类型保真 `==` 比较（`123 == "123"` → False，`123 == 123.0` → True）
- `contains`：不区分大小写子串匹配（`value.lower() in cell.lower()`），两侧必须均为字符串，非字符串单元格永不匹配

API 设计：
- `mode` 参数设置全局默认模式
- 条件元组支持 2 元素 `(field, value)`（用全局默认）或 3 元素 `(field, value, mode)`（逐条件覆盖）

**替代方案**：
- A) 仅 `exact` —— **不采用**：业务需求明确要求"匹配不到可以通过名称再匹配一下"，名称场景天然需要子串匹配。
- B) 支持正则 —— **不采用**：过度复杂，超出当前需求范围。
- C) `contains` 做区分大小写 —— **不采用**：实际业务场景（名称匹配）用户不会在意大小写，`"milk"` 和 `"Milk"` 都应命中；不区分更实用。

### D5: 结果排序策略

**选择**：按 `__priority__` 升序 → `__file__` 字典序，保证确定性输出。

**理由**：
1. 优先级升序让"最精确的匹配"排在最前面，符合用户直觉（先看到的是编码匹配的，不是名称模糊匹配的）。
2. 同级按文件名排序消除不确定性，便于测试断言和缓存。

### D6: 无匹配返回空 SheetData，不报错

**选择**：搜索结果为空时返回 `SheetData(columns=(...), rows=())`，columns 包含附加列和列名并集。

**理由**：搜索的语义是"找找看"，找不到是正常的业务结果而非异常。空 SheetData 让调用方可以统一处理（`if result.rows` 即可判断），不需要 try/except。

**替代方案**：
- A) 抛 `SearchError` —— **不采用**：将正常业务结果升级为异常，调用方被迫写冗余的异常处理。

### D7: 不依赖 DuckDB

**选择**：纯 Python 实现，逐文件读取 + 逐行匹配。

**理由**：
1. DuckDB 是可选 extra，新功能不应强制依赖。
2. 精确匹配和子串匹配在纯 Python 中实现简单且高效。
3. Excel 量级（通常 <10万行）纯 Python 完全够用。

**替代方案**：
- A) 走 Analyzer 注册所有 sheet 后 SQL 查询 —— **不采用**：强制 DuckDB 依赖，且优先级回退逻辑在 SQL 中表达别扭（需多层 LEFT JOIN + COALESCE）。

## Risks / Trade-offs

| 风险 | 处置 |
|---|---|
| **大目录性能**（数百文件 × 多 sheet） | 逐文件流式读取（openpyxl read_only），不一次性加载全部到内存；后续可加并发读取 |
| **列名冲突**（不同文件同列名不同含义） | 不做歧义消解，用户负责；文档标注 |
| **`__` 前缀列与用户数据列冲突** | 极低概率；若冲突则文档建议用户避免 `__` 前缀的列名 |
| **None 值密集**（列名并集导致大量 None） | 文档标注；用户可用 `project` 原语按需选列 |

## Migration Plan

纯新增，无破坏性改动：
1. 新增 `excelops/src/excelops/search.py`
2. 扩展 `excelops/errors.py` 新增 `SearchError`
3. 扩展 `excelops/__init__.py` 导出 `search_files` / `SearchError`
4. 新增 `excelOps/tests/test_search.py`

**回滚**：删除 `search.py`、`SearchError` 和测试即可，不影响现有代码。