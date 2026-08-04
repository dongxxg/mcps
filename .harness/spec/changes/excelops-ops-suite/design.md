## Context

excelOps Phase 1 已交付 `read → analyze → write` 骨干，脊椎类型为 `SheetData(columns, rows)`（frozen dataclass，tuple-based，不可变）。现有 `backends/` 提供 reader（openpyxl 流式）、analyzer（DuckDB 可选 extra）、writer（xlsxwriter CoW）、merger（两文件按 Sheet 合并）。

用户在实际业务中需要的是**多张报表的组合变换**：合并同类表、按多级编码查找价格、核算保质期分数、列投影、统计文字说明、多表转换合成采购/销售报表。本变更新增 `ops/` 模块，以 5 个纯 Python 变换原语 + 1 个输出原语为地基，6 项业务能力为配方（recipe）。

**已知约束**：
- `SheetData` 不可变契约 —— 所有原语必须返回新对象，不 mutate 输入
- backends 保持 policy-unaware —— ops 同样零 I/O、零副作用
- 不引入新依赖，不强制 `[duckdb]` extra
- merger.py 已有列对齐逻辑（`_align_columns` / `_remap_row`），需避免与 ops/union 发散

## Goals / Non-Goals

**Goals:**
- 新增 `ops/` 模块，提供可组合、可测试的纯函数业务操作层
- 6 项业务能力（report-combine / product-lookup / shelf-life / column-project / stats-narrate / table-transform）各自有独立配方
- ops/union 成为列对齐逻辑的唯一真相源，merger 调用它
- 聚合能力走现有 Analyzer，不在 ops 重复造轮子

**Non-Goals:**
- 不做 JSON/YAML DSL（recipe = Python 函数组合）
- 不做可视化 / MCP 工具封装（Phase 2）
- 不修改现有 backends 接口（纯新增）
- 不实现模板语言（narrate 限定为 Python 标准字符串格式化）
- 不做通用规则引擎（转换关系用原语组合表达）

## Decisions

### D1: 原语集定义 —— 5 变换原语 + 1 输出原语

**选择**：定义以下原语集：

| 原语 | 签名 | 语义 |
|---|---|---|
| `project(sd, columns, rename=None)` | `→ SheetData` | 选列 + 重排 + 重命名（关系代数 SELECT） |
| `union(tables, column_order=None)` | `→ SheetData` | 纵向堆叠，按列名对齐（UNION ALL） |
| `lookup(source, table, on, fetch, on_missing="null")` | `→ SheetData` | 优先级键匹配 + 列带回 |
| `derive(sd, name, fn)` | `→ SheetData` | 行级派生计算列，`fn(dict)→value` |
| `filter(sd, predicate)` | `→ SheetData` | 行级筛选，`predicate(dict)→bool` |
| `narrate(context, template)` | `→ str` | 模板文本渲染（输出原语，非变换） |

聚合（GROUP BY）不纳入原语集，recipe 层直接组合 Analyzer。

**替代方案**：
- A) 仅 5 原语（project / union / lookup / derive / narrate，无 filter）—— **不采用**：`filter` 是行级筛选原语（WHERE），6 项需求虽未明说"过滤"，但 table-transform 的条件分支（如"只保留过 1/2 保质期的"）几乎必然需要。没有 filter 的用户只能先 derive 布尔列再 project 掉，别扭且低效。10 行代码，值得加。
- B) 把聚合做成第 6 个纯 Python 变换原语 —— **不采用**：DuckDB 做聚合是它的主场（GROUP BY + 多聚合函数），纯 Python 重写 groupby 等于往 ops 里塞一个微型数据库，ROI 为负。Analyzer 已成熟且可选，recipe 层按需组合即可。
- C) 把 narrate 也做成 `SheetData → SheetData` 以保持契约统一 —— **不采用**：narrate 本质是数据→文本的归约，不是集合变换。强行让它返回 SheetData 是假统一。单独归类为"输出原语"，在文档和模块组织上标明即可。

**理由**：5 个变换原语覆盖关系代数的核心操作（SELECT / UNION / JOIN-like lookup / computed column / WHERE），加上输出原语 narrate 覆盖文本渲染。聚合走 Analyzer 是能力复用而非重复。

### D2: derive 的 fn 签名 —— fn(row_dict)→value

**选择**：`derive(sd, name, fn)` 中 `fn` 接收 `dict[str, Any]`（列名→值），返回新列值。内部通过 `dict(zip(columns, row))` 构造。

**替代方案**：
- A) `fn(row_tuple)` —— **不采用**：fn 必须知道列索引，脆弱。列顺序变化即坏，且用户写 `fn(row)` 时 `row[3]` 含义不明。
- B) `fn(**kwargs)` —— **不采用**：列名可能不合法为 Python 标识符（含空格/中文/数字前缀），`**kwargs` 会静默丢参数或抛 SyntaxError。

**理由**：`dict` 入参让 fn 按列名引用（`fn(r)` 内 `r["单价"]`），可读、健壮、与 SheetData 不可变哲学一致。中文列名天然支持。

### D3: lookup 预建索引策略

**选择**：`lookup` 对 table 的每个匹配列预建 `dict[value → row_index]` 索引，使单次查找从 O(n×m) 降为 O(n+m)。`on` 参数为有序列表 `[(src_col, table_col), ...]`，按序尝试，高优先级命中即停。多行匹配时取第一条（first-win，确定性）。

**替代方案**：
- A) 朴素嵌套循环（对 source 每行 × 对 table 每行逐键比较）—— **不采用**：1万×1万 = 1亿次比较，不可接受。报表场景虽通常 <10万行，但原语是通用基础设施，不能预设数据量上限。
- B) 走 Analyzer 做 JOIN —— **不采用**：优先级 fallback（试 A 再试 B 再试 C）在 SQL 里表达别扭（需多层 LEFT JOIN + COALESCE），且强制依赖 [duckdb] extra，与"原语层 duckdb-free"原则冲突。

**理由**：预建哈希索引是 Python 中等规模数据查找的标准做法，零额外依赖，性能确定。

### D4: ops/union 收复 merger 的列对齐逻辑

**选择**：`ops/union` 是列对齐逻辑的唯一真相源。`merger.merge_workbook` 内部调用 `ops/union` 完成数据层对齐，merger 仅负责 I/O 和样式保留（格式源文件、合并单元格、列宽等）。

**替代方案**：
- A) merger 保留自己的 `_align_columns` / `_remap_row`，ops/union 另起炉灶 —— **不采用**：两份列对齐逻辑必然发散（列对齐策略、None 填充、重复列行为不一致），维护负担加倍，且 bug 修复要同步两处。
- B) 删除 merger，全部用 ops/union 替代 —— **不采用**：merger 还承担样式保留（format source of truth）的 I/O 职责，ops/union 是纯函数不碰文件。职责不同，不能替代。

**理由**：单一真相源原则。merger 的样式保留是 I/O 层职责，列对齐是数据层职责，后者上提到 ops/union。Phase 2 实施时合并。

### D5: recipe = Python 函数组合，不建 DSL

**选择**：6 项业务能力的配方是普通 Python 函数，内部组合调用原语。例如：

```python
def purchase_requirement(price_sd, sales_sd, inventory_sd):
    matched = lookup(sales_sd, price_sd, on=[("条码","条码")], fetch=["单价"])
    with_stock = derive(matched, "库存", lambda r: r["库存量"] - r["预占"])
    return filter(with_stock, lambda r: r["库存"] < r["安全库存"])
```

**替代方案**：
- A) JSON/YAML 声明式 DSL（规则列表驱动）—— **不采用**：转换关系的形态不确定（字段映射/公式/单位换算/聚合/条件分支），建 DSL = 建模板语言 + 解析器 + 调试器，投入大且灵活性反低于直接写 Python。用户总能在 recipe 里写自定义函数兜底 20% DSL 覆盖不了的场景。
- B) 配置对象（dataclass 描述的规则集）—— **不采用**：比 JSON 略好但仍受限于预定义字段，公式和条件分支的表达力不足。

**理由**：原语签名统一为 `SheetData → SheetData`，可任意嵌套。Python 函数天然是最佳"组合子"，零解析成本，IDE 可补全、可调试、可单测。声明式 schema 是未来的事（等形态稳定后再抽象），现在不做。

### D6: narrate 归类为输出原语

**选择**：`narrate(context: dict, template: str) → str` 是输出原语，产出 str 而非 SheetData。限定使用 Python 标准字符串格式化（`str.format` 或 f-string 风格），不做模板语言。

**替代方案**：
- A) 用 `string.Template`（`$var` 语法）—— **不采用**：功能太弱，不支持数值格式化（`:.2f`、`:,`），stats-narrate 需求明确要求控制小数位和千分位。
- B) 用 Jinja2 —— **不采用**：引入新依赖，且模板语法超出"零新增依赖"约束。当前需求用 `str.format` 足够。

**理由**：`str.format` 是 Python 标准库，支持 `{name:.2f}` / `{name:,}` 等格式化规格，零依赖，满足需求。

## Risks / Trade-offs

| 风险 | 处置 |
|---|---|
| **merger ↔ ops/union 逻辑发散** | ops/union 作为唯一真相源；Phase 2 合并 merger 调用 |
| **lookup 纯 Python 性能** | 预建哈希索引，禁止朴素嵌套循环；大表（>10万行）recipe 可走 Analyzer |
| **聚合不在原语集** | recipe 层组合 Analyzer（可选 extra）；文档标注"需要聚合的 recipe 依赖 [duckdb]" |
| **derive 的 fn 签名不明确** | 定死 `fn(dict)→value`，测试覆盖中文列名/特殊字符列名 |
| **narrate 范围蔓延** | 限定 `str.format`，不做模板语言；超出需求时显式拒绝并建议用户端处理 |
| **大表 tuple-of-tuples 内存** | Excel 量级（10⁵行）够用，不提前优化；Phase 2 若遇瓶颈再评估 |

## Migration Plan

本变更是纯新增（无破坏性改动），无需迁移：
1. 新增 `excelops/ops/` 模块和 `tests/ops/` 测试
2. 扩展 `errors.py` 新增 `OpsError` 基类
3. 扩展 `__init__.py` 导出 ops 公共面
4. merger 对 ops/union 的调用合并推迟到 Phase 2（避免本次范围蔓延）

**回滚**：删除 `ops/` 模块及相关测试即可，不影响现有代码。

## 已决策的开放问题

1. **保质期单位** → 带单位字符串（"180天" / "12个月" / "2年"），纯数字默认=天。无法解析时抛 `TransformError`。（已更新 shelf-life spec）
2. **查找未匹配行的默认策略** → 默认 `on_missing="mark"`（标记 "__未找到__"），便于用户筛查。（已更新 product-lookup spec）
3. **table-transform 转换关系优先级** → 字段映射 > 公式 > 单位换算 > 聚合 > 条件分支。recipe 示例按此优先级设计。
