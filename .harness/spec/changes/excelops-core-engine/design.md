## Context

excelOps 的目标形态是操作 Excel 的 MCP（FastMCP + openpyxl + pandas + xlsxwriter + DuckDB）。兄弟项目 `serverOps/` 是已落地的 FastMCP 参考实现，其内部分层 `connectors → registry → tools → server` 被验证为干净的能力-暴露解耦。本变更只交付**底层能力层（Phase 1）**：一个纯 Python、无 FastMCP 依赖、可独立测试与复用的库，构成最薄的端到端闭环：`读(openpyxl) → 分析(DuckDB) → 写(xlsxwriter)`。

Excel 领域有两个库本身无法解决、必须由架构承担的风险：(1) 往返失真（公式/格式/类型在读写间静默丢失）；(2) 无事务安全（写中断即损坏文件）。本设计显式处理二者。

约束：Python ≥3.12；openpyxl/xlsxwriter 为纯 Python（跨版本稳定）；DuckDB 含 C 扩展（3.14 wheel 有风险）；目标目录 `excelOps/` 当前为空（绿地新建）。一台架构子代理对定稿设计做了对抗式复核，其结论已并入下文（标记「复核」）。

## Goals / Non-Goals

**Goals:**
- 打通 `read → analyze → write` 闭环，且三引擎经单一公共类型 `SheetData` 对接。
- 让 Phase 1 的代码**对 Phase 2 零返工**：backends policy-unaware、Analyzer 隐藏连接、errors 层级一次建全。
- 物理安全：Copy-on-Write 保证既有目标与输入永不损坏；类型保真保证往返不丢类型。
- 依赖可控：纯 Python 库为核心，重分析引擎为可选 extra。

**Non-Goals:**
- pandas（第二批）、FastMCP `tools/server`、`safety`/`audit`/`redaction`/`registry`（命名工作区）——均为 Phase 2。
- openpyxl「修改既有文件」写路径（Phase 1.5）。
- HTTP 鉴权、多端部署。

> **Phase 1 契约硬指标（复核提炼，违反则 Phase 2 必返工）**
> 1. `errors.py` 一次建全目标层级（含 `FileLocked`/`MissingDependency`/`SafetyError` 占位）。
> 2. `[duckdb]` extra 显式带 `pyarrow`（SheetData→表 的唯一干净路径）。
> 3. Copy-on-Write 写契约为 5 步（同卷 mkstemp / flush+fsync / 重试 / 失败清 .tmp / 返回路径）。
> 4. Analyzer 永不暴露 raw conn；会话级 ctx manager + lazy import duckdb。
> 5. 验收测试覆盖：类型保真 + 大文件流式 + 错误路径 + CoW 可观测。

## Decisions

### D1: 三层分层，backends 保持 policy-unaware

**选择**：`backends/`（能力实现，零 safety/audit/registry 依赖）→ （Phase 2）`tools/`（薄封装，在调用方上提 policy）。backends 内的 reader/analyzer/writer **不**调用安全检查、**不**写审计、**不**接受 `read_only` 之类 policy 参数。

**替代方案**：
- A) 让 backends 自己做安全检查（如 writer 内部判只读）—— 不采用：policy 与能力耦合，serverOps 实测证明其 `connectors/base.py` 是纯 ABC、对 safety 一无所知，policy 在 tool 层调用，切分更干净。
- B) 单层扁平结构（读写分析全塞一个模块）—— 不采用：三引擎职责正交，单层会超 800 行且无法独立测试。

**理由**：serverOps 的 `safety.py` 仅 ~40 行、单向依赖 errors+models，证明「能力层 policy-unaware、policy 上提到调用方」是低摩擦切分。Phase 2 上提 policy 时无需改动 Phase 1 代码。

### D2: SheetData(columns, rows) 作为无 pandas 的公共脊椎

**选择**：定义 `SheetData(columns: list[str], rows: list[list])` 为 reader→analyzer→writer 三者边界的唯一数据类型。不依赖 pandas，天然 JSON 可序列化（为 Phase 2 工具返回留路）。

**替代方案**：
- A) 用 `pandas.DataFrame` 当脊椎 —— 不采用：pandas 是第二批 extra，且 DataFrame 携带索引/dtype 复杂性，跨边界不必要；且 JSON 序列化需额外处理。
- B) 直接用 pyarrow Table 当脊椎 —— 不采用：Arrow 对 reader（openpyxl 产出 list）和 writer（xlsxwriter 消费 list）都不友好，徒增两端转换。
- C) 用 `list[dict]` —— 不采用：列名重复时不可靠，且按行访问性能差。

**理由**：`columns+rows` 对三引擎对称、最小、可测、可序列化。pandas 第二批接入时，它在 analyzer 内部作为「第二条策略」消化 SheetData，不改变脊椎。

### D3: DuckDB 经 pyarrow Table 注册（[duckdb] extra 带 pyarrow）

**选择**：SheetData → pyarrow Table → `duckdb.register(name, arrow_table)`，零拷贝。`pyarrow` 显式列入 `[duckdb]` extra 的依赖。

**替代方案**：
- A) `list[dict]` → DuckDB replacement scan —— 不采用：大表上 O(N) 额外拷贝。
- B) `CREATE TABLE` + `executemany INSERT` —— 不采用：需自行推断 schema，等于重写 DuckDB 类型推断。
- C) DuckDB 经 `spatial` 扩展直读 xlsx —— 不采用：依赖 GDAL，生产环境不稳，且绕开 openpyxl 的格式语义。

**理由**：Arrow 是 DuckDB 原生零拷贝路径，类型映射正确（datetime → TIMESTAMP）。DuckDB 不直读 xlsx 是铁律——openpyxl 永远是 xlsx 入口（见 D4）。

### D4: openpyxl 为 xlsx 唯一入口，data_only=True 默认

**选择**：所有 xlsx 读取经 openpyxl `read_only=True`（流式）+ `data_only=True`（取缓存值）。`data_only` 暴露为 read 参数可覆盖。

**替代方案**：
- A) `pandas.read_excel(engine="openpyxl")` —— 不采用：多一层包装、丢格式元数据，且绑死 pandas（与 D2 冲突）。
- B) 公式与值混读 —— 不采用：Phase 1 只需值，混读引入复杂度（YAGNI）。

**理由**：openpyxl 是唯一能完整还原 xlsx 内部结构的库；`read_only` 解耦内存（见大文件流式规格）。data_only=True 是分析场景的合理默认。

### D5: Copy-on-Write 五步写契约

**选择**：写出走「同目录 mkstemp → fdopen 写 → flush+fsync+close → os.replace（可短重试）→ 失败清 .tmp → 返回路径」五步。临时文件强制与目标同目录（同卷）。

**替代方案**：
- A) xlsxwriter 直接写目标 —— 不采用：写中断即留半损坏文件，无原子性。
- B) 用 `tempfile.NamedTemporaryFile(delete=False)` —— 不采用：Windows 下句柄占用有怪癖；改用 `mkstemp`+`os.fdopen`。
- C) 临时文件放系统 temp 目录 —— 不采用：通常与目标不同卷，`os.replace` 跨卷降级为拷贝+删除，原子性丧失。
- D) 数据库式事务回滚 —— 不采用：xlsx 无事务语义，不存在。

**理由**：Excel 无事务，C-o-W 是获得「物理不损坏既有目标」的唯一手段（类比 serverOps `db_query` 的回滚只读）。flush+fsync 保证 rename 前内容已落盘；同卷保证 `os.replace` 真原子。Windows 目标被占用（WinError 5）是 Excel 写自动化最高频失败，故短重试 + 映射为 `FileLocked`（见 D7）。

### D6: Analyzer 会话级上下文管理器，永不暴露 raw conn

**选择**：`Analyzer` 为上下文管理器，`__enter__` 惰性 import duckdb 并建连接，`__exit__` 关闭。构造函数接受 config 选内存库/文件库（默认内存）。公开面仅 `register/query/close`。

**替代方案**：
- A) 进程级单例连接 —— 不采用：DuckDB Python 单连接非线程安全；FastMCP 的 `def` tool 跑在 threadpool，共享单例会偶发崩溃，且逼 Phase 1 现在就解决线程安全。
- B) per-query 新建连接 —— 不采用：每次重新 register 浪费；可用但次优。
- C) 暴露 `az.conn` 供高级用户直操 —— 不采用：一旦暴露，后续切 cursor 池/换版本都是破坏性改动。

**理由**：会话级把「粒度」决定权交给调用方——Phase 1 纯库用 `with`，Phase 2 MCP 可选「每请求一会话」。隐藏 conn 使 Phase 2 对 Analyzer 零改动。DuckDB 缺失时 lazy import → `MissingDependency`（见 D7），`import excelops` 不受影响。

### D7: errors.py Phase 1 一次建全层级

**选择**：Phase 1 即建立完整异常树：`ExcelOpsError`（基类）下 `ReadError` / `WriteError` / `AnalyzeError` / `UnsupportedFormat` / `FileLocked` / `MissingDependency` / `SafetyError`（占位，Phase 1 不抛但先占名与 import 路径）。

**替代方案**：
- A) Phase 1 只建 `ExcelOpsError` 基类，子类 Phase 2 补 —— 不采用：若 reader 抛裸 `ValueError`/`FileNotFoundError`，Phase 2 的 redaction 装饰器无法可靠 `except ExcelOpsError`，且每个 raise 站点都要回改（典型「省 30 行，改 30 文件」）。

**理由**：空子类定义几乎零成本，但锁死未来 import 路径，撑起 Phase 2 的 redaction/audit/MCP 错误映射。serverOps 即从首版建全 5 子类。

### D8: 依赖分层（纯 Python 核心，C 扩展 extra，py≥3.12）

**选择**：核心依赖 `openpyxl` + `xlsxwriter`（纯 Python）；可选 extra `[duckdb]` = `duckdb` + `pyarrow`（C 扩展）；`[dev]` = pytest/ruff。`requires-python = ">=3.12"`。

**替代方案**：
- A) 全部核心依赖 —— 不采用：DuckDB/pyarrow 含 C 扩展，3.14 wheel 有风险，拖慢所有用户启动；违背 YAGNI。
- B) 锁 Python 3.14 —— 不采用：pandas/DuckDB 在 3.14 上 wheel 覆盖滞后；与 serverOps（`>=3.10`，README 推荐 3.12/3.13）一致。

**理由**：惰性导入 + extras 是 serverOps 已验证的精益安装模型；CI 矩阵跑 3.12/3.13/3.14，3.14 上 `[duckdb]` 测试允许单独标记。

### D9: write 返回结构化 WriteResult

**选择**：`write_workbook` 返回 `WriteResult(path, bytes_written, rows_written, source_ref)`，非裸 `Path`/`None`。

**替代方案**：
- A) 仅返回 `Path` —— 不采用：Phase 2 的 audit 装饰器需 bytes/rows 等元信息，返回结构化对象零成本且免回改签名。

**理由**：结构化结果让 Phase 2 audit 直接消费，不破坏 writer 签名。

### D10: Reader 承担 schema 纪律

**选择**：reader 负责：(a) 把参差行 pad 到 `len(columns)`；(b) 表头归一化（None/重名 → 合法唯一占位）；(c) 不对单元格做隐式 str 化（日期保持日期）。analyzer 不做隐式类型转换。

**替代方案**：
- A) 让 analyzer/DuckDB 自行推断并容忍参差 —— 不采用：列数不匹配直接建表失败；表头非法让 DuckDB 报错且难定位。

**理由**：把 schema 纪律集中在 reader（数据进入点），下游 analyzer/writer 可假设 SheetData 始终「列合法、唯一、行等长」。这是避免 Phase 2 类型 bug 指数增长的关键。

## Risks / Trade-offs

- **[pyarrow 额外依赖]** → 随 `[duckdb]` extra 安装，未装 duckdb 的用户不受影响（核心 read/write 不需要）。文档注明。
- **[Windows FileLocked 无法根治]** → Excel/杀软占用是间歇性 `PermissionError`。缓解：短重试 + 映射 `FileLocked` + 清理 .tmp；不试图「强行解锁」（危险）。文档说明用户需关闭 Excel。
- **[整数/浮点精度漂移]** → xlsx 固有缺陷（金额存 float 可能损精度）。缓解：文档记一笔，非本层能解。
- **[CoW 大文件多一次同卷拷贝]** → 安全优先于性能；同卷 rename 是常数级，可接受。文档注明权衡。
- **[read_only 流式不支持随机写/部分格式特性]** → Phase 1 只读，无影响；Phase 1.5 改既有文件需切非流式，届时评估。

## Migration Plan

- **部署**：全新包 `excelOps/`，无既有数据/服务需迁移。`pip install -e excelOps`（核心）或 `pip install -e 'excelOps[duckdb]'`（含分析）。
- **Phase 2 衔接**：backends policy-unaware，Phase 2 在 `tools/` 上提 safety/audit；Analyzer 隐藏 conn，MCP 化零返工；SheetData JSON 友好，直接作工具返回。
- **回滚**：本变更新增独立包，删除 `excelOps/` 目录即完全回滚，不影响 `serverOps`。

## Open Questions

- **空 SheetData 写出语义**：倾向「空 rows → 写表头-only 表」；「空 columns 且空 rows → `WriteError`」。待实施时定并加测试。
- **表头归一化是否需可逆还原**（writer 还原原表头）：Phase 1 倾向简单去重+占位、不还原，文档注明；如 Phase 2 有诉求再增强。
- **`data_only` 默认值**：Phase 1 默认 `True`（取缓存值）且可参数覆盖——已在规格固化。
