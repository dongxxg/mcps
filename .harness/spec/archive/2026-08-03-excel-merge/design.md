## Context

excelOps Phase 1 提供**读取（openpyxl 流式）→ 分析（DuckDB）→ 写出（xlsxwriter CoW）**管道。合并功能需要保留源文件视觉格式，但 xlsxwriter 是只写引擎无法读格式，openpyxl 流式模式不加载样式。因此合并功能需要一个**独立的 openpyxl 读写引擎**，不干扰现有管道。

### 约束（PM 确认）

1. **全量视觉格式保留**：列宽 / 颜色 / 合并单元格 / 行高 / 单元格样式
2. **Sheet 名精确配对**：按名称匹配，单方有的 Sheet 原样保留
3. **Union 列对齐**：列头取并集，缺失填 None，file_b 新列追加到末尾
4. **不去重**：保留所有行

## Goals / Non-Goals

**Goals:**
- 两个 xlsx 文件纵向合并为一个全新 xlsx
- 完整保留 file_a 的视觉格式
- Union 列对齐 + 不去重
- 独立模块，不污染现有 reader/writer/analyzer
- 公开 API：`merge_workbook(path_a, path_b, out_path) -> MergeResult`

**Non-Goals:**
- 不修改现有 reader/writer/analyzer 任何代码
- 不实现 CoW 原子写（openpyxl 直写全新文件）
- 不处理公式重算（`data_only=True` 读缓存值）
- 不处理 >100MB 超大文件（标注为 Phase 2 优化）
- 不处理图表/图片/条件格式/数据验证（openpyxl 部分支持，标注已知限制）

## Decisions

### D1: 合并引擎选型——openpyxl 单一引擎 vs openpyxl+xlsxwriter 双引擎

**选择**：openpyxl 单一引擎（读 file_a + 写输出），file_b 用现有 streaming reader 读取数据

**替代方案：**
- A) 纯 openpyxl 双文件全量加载 — file_b 也用 openpyxl 全量加载。**未采用**：file_b 只需数据不需要格式，streaming reader 内存更优
- B) openpyxl 读 file_a 元数据 + xlsxwriter 写输出 — 跨引擎样式转换。**未采用**：PM 要求保留颜色/合并单元格等完整视觉格式，xlsxwriter 格式 API 与 openpyxl 格式对象不兼容，转换层复杂度高且易丢失

**理由**：openpyxl 同时支持格式读写，单一引擎避免跨引擎转换；file_b 用 streaming reader 只在需要列对齐时读一次，内存最优。

### D2: 合并基准——以 file_a 为主 vs 新建空白工作簿

**选择**：以 file_a 为基准（openpyxl 加载 file_a → 修改 → save 到 out_path）

**替代方案：**
- A) 新建空白 openpyxl Workbook，从 file_a 复制 Sheet 结构 + 数据 + 格式，再追加 file_b — **未采用**：复制格式代码量更大，且 openpyxl 的 `copy_worksheet` 跨 workbook 不支持
- B) 以 file_b 为基准 — **未采用**：PM 未区分主次，file_a 为基准是自然选择（调用顺序）

**理由**：openpyxl 修改已有 workbook 是最小代码路径；file_a 天然成为格式 source of truth。

### D3: 列对齐策略——union vs intersection

**选择**：union（列头取并集），缺失填 None，file_b 新列追加到末尾

**替代方案：**
- A) intersection（只保留两文件共有列）— **未采用**：PM 明确"保留空列"，intersection 会丢弃数据
- B) 以 file_b 列顺序为准 — **未采用**：file_a 为基准，列顺序应保持 file_a 稳定

**理由**：PM 决策记录明确要求 union + 保留空列。

### D4: 大文件策略——读 file_b 流式 vs 全量

**选择**：file_b 用现有 `reader.read_sheet(streaming)` 读为 SheetData，file_a 用 openpyxl 全量加载

**替代方案：**
- A) 两文件均用 openpyxl 全量加载 — **未采用**：内存 2× 成本，file_b 不需要格式
- B) 两文件均流式 + 写出用 xlsxwriter — **未采用**：xlsxwriter 无法保留格式（违反 PM 硬需求）

**理由**：平衡内存与格式保真。file_a 全量加载的内存代价换取完整格式保留；file_b 流式读取减少一半内存压力。

### D5: 模块组织——独立 merger.py vs 扩展现有模块

**选择**：独立 `backends/merger.py` 模块

**替代方案：**
- A) 扩展 `writer.py` 增加 `merge_workbook` — **未采用**：writer 是 xlsxwriter 专用，合并用 openpyxl，职责混杂
- B) 扩展 `reader.py` 增加合并函数 — **未采用**：reader 是只读引擎，合并涉及写入，违反单一职责

**理由**：符合 D1 决策的"按操作命名"惯例（reader/analyzer/writer/merger），独立模块更易测试维护。

## Risks / Trade-offs

| 风险 | 缓解 |
|------|------|
| openpyxl 非流式，大文件内存 2× | Phase 1 接受；文档标注限制；Phase 2 可优化为分块 |
| 合并单元格跨越数据行边界 | 检测合并区域，追加行后调整合并范围（或标注跨合并区域追加为已知限制） |
| 条件格式/数据验证不保留 | openpyxl 部分支持，标注为已知限制 |
| 公式不重算 | `data_only=True` 读缓存值，合并后公式丢失（标注已知限制） |
| 放弃 CoW 原子写 | 全新文件写入，失败不污染源文件；目标路径若存在会被覆盖（标注行为） |

## Migration Plan

无破坏性变更——纯新增功能，无需迁移。

部署步骤：
1. 新增 `backends/merger.py`、扩展 `errors.py`、更新 `__init__.py`
2. 新增 `tests/test_merger.py`
3. ruff + pytest 全绿
4. 合并到主干

回滚：删除 `merger.py` 及相关导出即可，不影响现有功能。

## Open Questions

1. **合并单元格跨数据行**：如果 file_a 表头行有合并单元格（如 A1:B1 合并），追加 file_b 数据行后是否扩展合并区域？→ **决策：不扩展，合并区域保持 file_a 原始范围，数据行从合并区域下方开始**
2. **file_b 新列的格式**：union 后 file_b 独有的列在输出中应用什么样式？→ **决策：应用 openpyxl 默认样式（与 file_a 其他列的"默认"一致）**
3. **输出文件已存在**：是否覆盖？→ **决策：openpyxl `save()` 直接覆盖，符合"全新 Excel"语义**
