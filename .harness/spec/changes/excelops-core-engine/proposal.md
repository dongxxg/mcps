## Why

excelOps 的最终形态是一个操作 Excel 的 MCP（FastMCP + openpyxl + pandas + xlsxwriter + DuckDB），但 Excel 领域有两个**库本身无法解决、必须在架构层处理**的风险：

1. **往返失真** —— 在「读 → 改 → 写」之间，公式、格式、图表极易被静默丢失，模型一句话就可能把用户的精美报表洗成裸数据。
2. **无事务安全** —— Excel 文件没有回滚机制，一次写中断就直接损坏整个工作簿。

参考兄弟项目 serverOps 已被验证的 `connectors → tools` 接缝（能力实现与 MCP 暴露解耦），本变更**先打通底层能力层**：把它做成一个纯 Python、可独立测试、可被任意脚本复用的库，把 FastMCP / 安全策略 / 审计等 MCP 关注点显式推迟到后续变更。这样引擎本身能在不背契约包袱的前提下做扎实，也为 Phase 2 封装 MCP 留出稳定的锚点。

## What Changes

- **新建 `excelOps` 包**（src-layout），沿用 serverOps 的目录约定与 `errors` 层级范式。
- **新建能力层 `backends/`**：`reader`（openpyxl 读取）、`analyzer`（DuckDB SQL 分析）、`writer`（xlsxwriter 写出），按「操作」命名而非按库名（库是实现细节）。
- **引入公共脊椎类型 `SheetData`**（`columns` + `rows`），在**不依赖 pandas** 的前提下贯通三引擎，且天然 JSON 友好（为 Phase 2 工具返回留路）。
- **写语义统一为 Copy-on-Write**：先写 `.tmp` 再原子替换，输入文件永不损坏；所有写函数返回最终路径，不做就地修改。
- **确立 xlsx 入口铁律**：openpyxl 是 xlsx 的唯一读取入口（DuckDB 经 `SheetData` 注册成表后做 SQL，不直读 xlsx —— 因 spatial 扩展不稳）。
- **依赖分层**：openpyxl + xlsxwriter 为核心依赖（纯 Python，跨版本稳定）；DuckDB 为可选 extra `[duckdb]`（C 扩展，Python 3.14 wheel 存在风险）。`requires-python = ">=3.12"`。

**显式不在本变更范围（推迟到后续变更）**：pandas；FastMCP `tools/` + `server.py` + `__main__.py`；`safety`（路径沙箱/只读开关）、`audit`、`redaction`；`registry`（命名工作区）；openpyxl「修改已有文件」写路径；HTTP 鉴权。这些均不阻塞本变更的闭环验收。

## Capabilities

### New Capabilities

- `excel-read`: 经 openpyxl 读取 xlsx 工作簿/工作表（流式 `read_only`、工作表枚举、工作表元信息、保真取数），产出 `SheetData`。
- `excel-analyze`: 经嵌入式 DuckDB 做 SQL 分析；将 `SheetData` 注册为可查询表、执行参数化 SQL、结果回 `SheetData`。
- `excel-write`: 经 xlsxwriter 写出全新 xlsx 工作簿，采用 Copy-on-Write 安全语义，支持多表输出，返回最终路径。

### Modified Capabilities

无。本变更为全新能力，仓库内无既有 excelOps 规格（`rd list` 为空，`excelOps/` 目标目录尚为空）。

## Impact

- **新增代码**：`excelOps/pyproject.toml`、`excelOps/src/excelops/{__init__,errors}.py`、`excelOps/src/excelops/backends/{models,reader,analyzer,writer}.py`、`excelOps/tests/`。
- **新增依赖**：`openpyxl`、`xlsxwriter`（核心）；`duckdb`（可选 extra `[duckdb]`）。
- **对外 API**：一个纯 Python 库的公开接口（read / analyze / write），**尚无 FastMCP**。
- **架构复刻**：沿用 serverOps 的 src-layout、errors 层级、optional extras + 惰性导入范式；但**不复刻**其连接池/凭据模型（Excel 是无状态本地文件，无连接、无凭据）。
- **运行时**：Python >=3.12；CI 应覆盖 3.12/3.13/3.14（3.14 上 `[duckdb]` 允许单独标记）。
