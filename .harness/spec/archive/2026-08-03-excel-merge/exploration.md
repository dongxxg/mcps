# Excel Merge — 架构探索视角

> 生成时间：2026-08-03
> 变更：excel-merge（将两个相同标题格式的 Excel 合并为新文件）
> 阶段：explore

---

## 1. 架构定位与职责边界

### 1.1 模块概览

`excelOps` 是一个 **纯 Python 的 Excel 能力库**（Phase 1），定位为底层引擎层。它**不是** MCP 服务器，不处理安全策略、审计、鉴权——这些推迟到 Phase 2。

```
excelOps/
├── pyproject.toml              # 包元数据 + 依赖分层
├── src/excelops/
│   ├── __init__.py             # 公开 API 门面
│   ├── errors.py               # 完整异常层级（7 个子类）
│   └── backends/
│       ├── __init__.py         # policy-unaware 声明
│       ├── models.py           # SheetData / SheetMeta / WriteResult
│       ├── reader.py           # openpyxl 读取（流式）
│       ├── analyzer.py         # DuckDB SQL 分析（可选 extra）
│       └── writer.py           # xlsxwriter 写出（Copy-on-Write）
└── tests/                      # pytest 测试套件
```

### 1.2 核心能力（Phase 1 已实现）

| 能力 | 引擎 | 入口 | 说明 |
|------|------|------|------|
| **读取** | openpyxl | `list_sheets`, `read_sheet`, `sheet_meta` | 流式读取（`read_only=True`），产出 `SheetData` |
| **分析** | DuckDB | `Analyzer.register`, `Analyzer.query` | SQL 分析，可选 extra `[duckdb]` |
| **写出** | xlsxwriter | `write_workbook` | Copy-on-Write 安全语义，返回 `WriteResult` |

### 1.3 设计哲学

- **单一脊椎类型**：`SheetData(columns: tuple[str], rows: tuple[tuple])` — 无 pandas、不可变、JSON 友好
- **Backends policy-unaware**：能力层不做安全检查/审计，Phase 2 在 tool 层叠加
- **Reader 承担 schema 纪律**：header 归一化 + ragged pad，下游可假设数据 well-formed
- **Copy-on-Write**：同卷 mkstemp → flush+fsync → os.replace → 失败清 .tmp

---

## 2. 关键集成点与契约

### 2.1 依赖拓扑

```
excelOps 内部依赖链：

    reader.py ──→ openpyxl (核心)
    analyzer.py ──→ duckdb + pyarrow (可选 extra [duckdb]，惰性导入)
    writer.py ──→ xlsxwriter (核心)
    
    三者通过 SheetData (models.py) 对接
```

**对外零内部模块依赖**：excelOps 是独立包，不依赖 serverOps 或仓库内其他代码。

### 2.2 被依赖关系

| 消费方 | 关系 | 状态 |
|--------|------|------|
| `serverOps` | 无直接依赖 | serverOps 是独立的 MCP 服务器（远端运维），与 excelOps 无交叉 |
| 仓库内其他代码 | 无 | excelOps 是仓库内唯一的 Excel 处理模块 |
| 未来 Phase 2 | `tools/` 层封装 | 将在 excelOps 上层构建 FastMCP server |

**结论**：excelOps 当前是**叶模块**——只被未来代码依赖，不依赖同仓库其他模块。合并功能的集成完全在 `excelOps` 内部完成。

### 2.3 对外契约（公开 API）

```python
# 读取
list_sheets(path) -> list[str]
read_sheet(path, sheet, header=True, data_only=True) -> SheetData
sheet_meta(path, sheet) -> SheetMeta

# 分析
Analyzer(database=":memory:")  # 上下文管理器
  .register(name, sheet_data) -> None
  .query(sql, params=None) -> SheetData

# 写出
write_workbook(path, sheets: dict[str, SheetData], source_ref=None) -> WriteResult

# 错误层级
ExcelOpsError
├── ReadError
├── WriteError
├── AnalyzeError
├── UnsupportedFormat
├── FileLocked
├── MissingDependency
└── SafetyError  # 占位，Phase 1 不抛出
```

---

## 3. 已知技术约束与架构决策

### 3.1 关键架构决策（D1–D10）

| 决策 | 内容 | 对合并功能的影响 |
|------|------|------------------|
| **D2** | `SheetData(columns, rows)` 为唯一脊椎，无 pandas | 合并操作的数据结构基础 |
| **D4** | openpyxl 为 xlsx **唯一入口**，`read_only=True` 流式 | 合并的读取必须走 openpyxl |
| **D5** | Copy-on-Write 五步写契约 | 合并输出的安全保障 |
| **D10** | Reader 承担 schema 纪律（header 归一化 + ragged pad） | 合并前需确认两文件 header 语义一致 |

### 3.2 格式处理：当前能力与合并需求的鸿沟

**当前 writer 的格式能力：**
- 仅处理 **日期 number format**（`yyyy-mm-dd` / `yyyy-mm-dd hh:mm:ss`）
- **不保留**源文件的任何格式：列宽、字体、颜色、合并单元格、条件格式、冻结窗格、筛选器等

**合并任务验收标准中的格式要求：**
> "保留源格式（列宽、样式、合并单元格等）"

**架构冲突**：
- `xlsxwriter` 是**只写引擎**——可以创建新格式，但**无法读取**已有格式
- `openpyxl` 可以读取格式，但当前 reader 使用 `read_only=True` 流式模式，**不加载样式信息**
- `openpyxl` 的「修改已有文件」写路径被**显式推迟**（Non-Goal，标注为 Phase 1.5）

**结论**：格式保留是本次合并功能的**最大架构挑战**，需要以下之一：
1. 扩展 reader 为非流式模式以捕获格式元数据
2. 引入 openpyxl 写路径作为第二写引擎
3. 重新协商验收标准（格式保留的范围）

### 3.3 大文件处理策略

| 方面 | 当前实现 | 对合并的影响 |
|------|----------|--------------|
| 读取 | `read_only=True` 流式，峰值内存与文件大小解耦 | 合并两个大文件时内存 ≈ max(file1, file2)，可接受 |
| 写出 | xlsxwriter 在内存中构建完整 buffer，然后落盘 | 合并后 buffer = 两文件数据总和，注意内存峰值 |
| 测试基线 | 100k 行测试通过，峰值 < 512MB | 合并场景下需重新验证 |

**关键风险**：`write_workbook` 的 `_build_bytes` 先在内存构建完整 xlsx buffer。合并两个 10 万行的文件，buffer 可能达数百 MB。

### 3.4 类型保真

Reader → Analyzer → Writer 全链路保持类型：
- `date` / `datetime` → 经 `write_datetime` 写入，读回仍为日期对象
- `float` / `int` / `str` / `None` → 原样保留

合并操作本身不涉及类型转换，类型保真不成问题。

---

## 4. 现有 Excel 能力清单

### 4.1 已支持的操作

| 操作 | 函数/方法 | 状态 |
|------|-----------|------|
| 列出工作表 | `list_sheets(path)` | ✅ 完整 |
| 读取工作表为结构化数据 | `read_sheet(path, sheet, header, data_only)` | ✅ 完整 |
| 查询工作表维度 | `sheet_meta(path, sheet)` | ✅ 完整 |
| SQL 聚合分析 | `Analyzer.query(sql)` | ✅ 完整 |
| 写出多表工作簿 | `write_workbook(path, sheets)` | ✅ 完整 |
| header 归一化（去重/空值处理） | reader 内部 `_normalize_header` | ✅ 完整 |
| ragged 行补齐 | reader 内部 `_fit` | ✅ 完整 |
| 空工作表（仅 header）写出 | `write_workbook` | ✅ 完整 |
| 文件损坏检测 | `UnsupportedFormat` | ✅ 完整 |
| 目标锁定检测 | `FileLocked` | ✅ 完整 |

### 4.2 明确不支持的操作（Phase 1 Non-Goals）

| 操作 | 状态 | 备注 |
|------|------|------|
| 修改已有文件 | ❌ 不支持 | Phase 1.5，当前只写全新文件 |
| 读取/保留单元格样式 | ❌ 不支持 | `read_only` 模式不加载样式 |
| 读取/保留合并单元格 | ❌ 不支持 | 同上 |
| 读取/保留列宽 | ❌ 不支持 | 同上 |
| 读取/保留公式 | ❌ 不支持 | `data_only=True` 默认取值 |
| 图表/图片 | ❌ 不支持 | — |
| pandas DataFrame 直出 | ❌ 不支持 | 第二批 extra |
| CSV/ODS 等其他格式 | ❌ 不支持 | 仅 xlsx |

### 4.3 合并功能所需能力 vs 现有能力对照

| 合并需求 | 所需能力 | 现有支持 | 差距 |
|----------|----------|----------|------|
| 读取两个 Excel 的指定 sheet | `read_sheet` × 2 | ✅ | 无 |
| 校验 header 一致性 | header 元数据对比 | ✅（reader 已归一化） | 无 |
| 纵向拼接 rows | `SheetData.rows` 拼接 | ✅（tuple 拼接） | 无 |
| 写出合并结果 | `write_workbook` | ✅ | 无 |
| **保留列宽** | 读取列宽 + 写入列宽 | ❌ reader 不读列宽，writer 不设列宽 | **需扩展** |
| **保留单元格样式** | 读取样式 + 写入样式 | ❌ 两端都不支持 | **需扩展** |
| **保留合并单元格** | 读取合并信息 + 写入合并 | ❌ 两端都不支持 | **需扩展** |
| 大文件内存控制 | 流式读 + buffer 写出 | ✅ / ⚠️ | 需验证 buffer 峰值 |

---

## 5. 扩展点分析

### 5.1 新功能接入位置

合并功能应作为**新的 backend 模块**或**现有模块的扩展函数**接入：

```
方案 A：新模块
excelops/backends/
├── merger.py          # 新增：merge_workbooks / merge_sheets
└── formatter.py       # 新增：格式读取/写入（若需格式保留）

方案 B：现有模块扩展
excelops/backends/
├── reader.py          # 扩展：增加 style-aware 读取模式
├── writer.py          # 扩展：增加格式参数 + set_column 等
└── models.py          # 扩展：增加 SheetStyle 等元数据类型
```

**推荐方案 A**（新模块），理由：
- 符合 D1 决策的"按操作命名"惯例（reader/analyzer/writer/merger）
- 不污染已有模块的职责边界
- 格式保留逻辑复杂度高，独立模块更易测试和维护

### 5.2 格式保留的技术路径

若验收标准坚持格式保留，有以下技术路径：

| 路径 | 描述 | 代价 |
|------|------|------|
| **A. openpyxl 双引擎** | 用 openpyxl（非流式）读 + 写，xlsxwriter 退为可选 | 重写 writer，放弃 CoW 原子性优势，大文件内存暴涨 |
| **B. openpyxl 读 + xlsxwriter 写** | openpyxl 读元数据（样式）→ 转为 xlsxwriter 格式 → xlsxwriter 写出 | 需实现样式转换层（~200 行），CoW 保留，但只读一次文件 |
| **C. 扩展 reader 为可选 style-mode** | `read_sheet(..., style_info=True)` 时返回额外元数据 | 需修改 reader（非流式分支），影响现有 reader 契约 |
| **D. 重新协商验收标准** | 仅保数据 + 日期类型，格式需另行处理 | 最小工作量，但可能不满足 PM 期望 |

### 5.3 SheetData 扩展方向

若需携带格式信息，`SheetData` 需扩展：

```python
@dataclass(frozen=True)
class SheetData:
    columns: tuple[str, ...]
    rows: tuple[tuple, ...]
    # 新增（可选扩展）：
    # column_widths: tuple[float, ...] | None = None
    # merged_cells: tuple[tuple[int, int, int, int], ...] | None = None
    # cell_styles: dict[tuple[int, int], CellStyle] | None = None
```

**注意**：`SheetData` 是 frozen dataclass，新增字段需保持向后兼容（默认 None）。

---

## 6. 关键风险与架构疑问

### 6.1 高风险项

1. **格式保留 vs 架构简洁性**：xlsxwriter 无法读格式，openpyxl 流式不加载样式。保留格式需要引入第二读引擎或切换模式，显著增加复杂度。

2. **大文件写出内存**：xlsxwriter 在内存构建完整 buffer。合并两个大文件时 buffer 峰值 = 两文件数据之和，可能触发 OOM。

3. **header 语义一致性校验**：两个文件的"相同标题格式"需要严格定义——是精确匹配？忽略大小写？归一化后匹配？当前 reader 会归一化 header，但合并前需明确语义。

### 6.2 待 PM 确认的架构问题

1. **格式保留的范围**：验收标准要求"保留源格式（列宽、样式、合并单元格等）"——这是硬性需求还是期望？如果仅保留列宽 + 合并单元格（不含字体/颜色），技术复杂度大幅降低。

2. **合并后 sheet 结构**：两个文件的多个 sheet 如何合并？是按 sheet name 配对合并？还是只合并指定 sheet？还是所有 sheet 按位置合并？

3. **冲突处理**：如果两个文件的同一 sheet 列数不同（但 header 名部分重叠），是取并集（缺值填 None）还是报错？

4. **大文件定义**：验收标准提到"处理大文件时内存占用合理"——具体的文件大小阈值是多少？是否需要支持 >100MB 的文件？

---

## 7. PM 决策记录（2026-08-03）

| 问题 | PM 决策 | 影响 |
|------|---------|------|
| 格式保留范围 | **全量视觉格式**：标题结构 + 列宽 / 颜色 / 合并单元格 | 必须用 openpyxl 读写引擎，xlsxwriter 不可用 |
| 多 Sheet 配对 | **按 Sheet 名精确配对** | 需 union sheet 集合 |
| 列差异（A 多一列） | **保留空列**（union of columns，缺失填 None） | 列对齐逻辑用 union 而非 intersection |
| 重复数据 | **不去重** | 直接拼接，无需 dedup 逻辑 |

## 8. 最终技术决策

**选定方案：openpyxl 读写引擎（方案 A 变体）**

理由：
- PM 确认格式保留为**硬需求** → xlsxwriter 不可用
- openpyxl 同时支持读 + 写 → 单一引擎，无需跨引擎样式转换
- 以 file_a 为格式基准，file_b 用现有 streaming reader 读取数据
- 合并逻辑独立为 `backends/merger.py`，不污染现有 reader/writer

**架构变更**：
```
新增：backends/merger.py      — openpyxl 读写合并引擎
新增：MergeError(ExcelOpsError) — 合并专用异常
扩展：__init__.py             — 导出 merge_workbook
不变：reader / writer / analyzer / models（完全不改）
权衡：放弃 CoW 原子写（merger 写全新文件，源文件不受影响）
```

**大文件策略**：
- 读 file_b 用现有 streaming reader（内存友好）
- 写 file_a 用 openpyxl 全量加载（格式保真代价）
- 10 万行级别可接受，更大文件标注为 Phase 2 优化项

## 9. 总结

excelOps Phase 1 数据管道完整。合并功能的核心挑战是**格式保留**——已决策切到 openpyxl 引擎。

实现路径：
1. 新增 `backends/merger.py`（~150 行）
2. 新增 `MergeError` 异常
3. 接入公开 API（`__init__.py`）
4. 完整测试覆盖（正常 + 边界 + 格式保留验证）

预估工作量：~400 行新增代码。
