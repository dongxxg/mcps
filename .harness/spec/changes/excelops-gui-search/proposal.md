## Context

excelOps Phase 1 已交付完整的 read → analyze → write 纯 Python 库，Phase 1.5 交付了跨文件搜索 `search_files()`。但 excelOps **目前只有两个调用方式**：写 Python 代码调用，或通过 MCP 协议（Phase 2 计划）。普通用户无法在没有编程能力的前提下直观地搜索 Excel 文件。

用户需要**一个桌面客户端**，打开即用，不需要写代码。首期实现搜索功能，但客户端必须是**可扩展的操作框架**——搜索只是第一个操作，后续还会有过滤、转换、统计等。

**已知约束**：
- `SheetData` 不可变契约，所有数据流转统一用 frozen dataclass
- `excelops` library 必须保持零 GUI 依赖（`pip install excelops` 不拉入 PySide6）
- GUI 层**零业务逻辑**，只调用 library 公开 API
- 大文件场景需要流式分页，不能一次加载全部到 QTableView
- PyQt 选型：PySide6（Qt 官方绑定，LGPL 协议）
- UI 风格：浅色简洁风（Google Sheets / Notion 感）

## Goals / Non-Goals

**Goals:**
- 新增独立 `excelops_gui` 包（PySide6），与 `excelops` 同仓库
- 三区布局 MainWindow：左导航（文件/Sheet 树）| 中数据区（QTableView + 分页）| 右操作面板（可切换）
- 搜索功能两种模式：单文件浏览搜索 + 目录跨文件搜索
- 一键导出搜索结果到新 xlsx
- 操作面板可插拔架构（注册表模式），支持后续添加过滤/转换/统计面板
- 浅色简洁风主题（light.qss）
- 搜索操作后台线程执行，不阻塞 UI

**Non-Goals:**
- 过滤/转换/统计面板的实现（Phase 2，只提供基类接口）
- MCP 入口（独立 change）
- 跨平台打包（PyInstaller / 分发）
- 真正的搜索取消能力（library 层不支持，首期接受限制）
- 多用户/多标签页并发

## Decisions

### D1: GUI 包独立，同仓库

**选择**：在 `excelOps/src/` 下新增 `excelops_gui/` 包，独立 `pyproject.toml` 放在 `excelOps/` 根目录（通过 `[tool.setuptools.packages.find]` 的 `include` 限定只找 `excelops*` 包）。GUI 声明为 `excelops[gui]` 可选 extra。

**理由**：
1. excelOps 已含两个包（`excelops` 库 + 测试），第三包放在同仓库符合已有模式
2. 同 pyproject.toml 通过 extras 区分，`pip install excelops` 仍无 GUI 依赖，`pip install 'excelops[gui]'` 才装 PySide6
3. 未来若需独立发布/独立 CI 再迁出，当前降低仓库复杂度

**依赖方向**：`excelops_gui` → `excelops`（单向），`excelops` **永远不** import `excelops_gui`。

**替代方案**：
- A) 新建独立目录 `excelOpsGui/`（镜像 serverOps）—— **不采用**：过度设计，GUI 是 library 的 UI 壳，不是独立服务
- B) 合并到 `excelops` 包内（`excelops.gui` 子包）—— **不采用**：违反 Phase 1 "library only" 承诺，`pip install excelops` 会强制安装 PySide6

### D2: 三区布局 MainWindow

**选择**：`QMainWindow` + `QSplitter` 实现三区：
- **左侧**（窄）：`QTreeView` 文件/Sheet 导航，支持文件打开、Sheet 切换
- **中间**（宽）：`QTableView` + `PaginatedModel`（500 行/页），底部分页控件
- **右侧**（中）：操作面板区，顶部操作选择器（搜索/过滤/转换 Tab），下方当前操作的参数面板

**理由**：操作面板可切换，数据区和导航区始终可见。比纯 Tab 式布局更优——操作增多时 Tab 爆炸，三区布局只增右侧面板。

```
┌─────────────────────────────────────────────────────────────────┐
│  TopBar: [打开文件/目录] [当前文件标签] [状态] [导出]           │
├──────────┬──────────────────────┬──────────────────────────────┤
│ 文件/    │  QTableView          │  操作面板                    │
│ Sheet    │  PaginatedModel      │                              │
│ 树       │  500行/页            │  [搜索] ← 当前              │
│          │                     │  [过滤] ← 未来               │
│          │                     │  [转换] ← 未来               │
│          │  [首页][上] 1/3 [下] │  ─────────────────          │
│          │  共 1250 行          │  [搜索参数区]                │
└──────────┴──────────────────────┴──────────────────────────────┘
```

### D3: 操作面板注册表模式

**选择**：装饰器注册表（`@register_panel("search")`），基类 `BasePanel` 抽象 `build_ui()` + `execute(context)`。

**理由**：首期只有搜索，插件文件扫描对单操作过度设计。注册表模式新增操作只需一行装饰器，与未来 MCP tool 注册一一对应。

```python
class BasePanel(ABC):
    name: str
    title: str
    @abstractmethod
    def build_ui(self) -> QWidget: ...
    @abstractmethod
    def execute(self, ctx: PanelContext) -> PanelResult: ...

_panel_registry: dict[str, type[BasePanel]] = {}

def register_panel(name: str):
    def decorator(cls):
        _panel_registry[name] = cls
        return cls
    return decorator
```

### D4: 分页策略 — 预扫描总数 + 显示层切片

**选择**：`read_sheet()` / `search_files()` 返回完整 `SheetData`，`PaginatedModel` 持有引用，按 `rows[start:start+500]` 切片显示。总数 = `len(sd.rows)`，零额外成本（openpyxl `read_only=True` 已流式读取）。

**理由**：
1. `SheetData.rows` 是 `tuple[tuple, ...]`，切片创建新 tuple 但底层 row tuple 共享引用，内存开销极小
2. 架构分层清晰：读取全量是 library 职责，分页是 GUI 职责
3. 无需为 `read_sheet` 新增 `max_rows` 参数（不破坏 Phase 1 API）

**页大小**：默认 500 行/页（常量，可在配置中覆盖）。

### D5: 线程模型 — QThread Worker + Signal/Slot

**选择**：`QThread` + 自定义 `QObject` Worker，发出 `progress(int, str)` / `result(SheetData)` / `error(str)` 三个 signal。任何 >100ms 的操作（搜索、大文件读取、导出）必须进后台线程。

**理由**：PySide6 的 signal/slot 自动处理跨线程排队，QThread 比 QRunnable 生命周期管理更清晰。

**取消能力**：首期接受"无法真正取消"限制（`_match_rows` 无取消点），Worker 的 `cancel()` 仅在 signal 层面阻止 UI 使用结果。UI 上以"搜索中..."状态 + 禁用重复触发降低误操作。

### D6: 浅色简洁风主题

**选择**：QSS 样式表 `light.qss`，定义在 `excelops_gui/theme/`。色板：白底 (#FFFFFF) + 浅灰分区 (#F5F5F5) + 细边框 (#E0E0E0) + 主色 (#1A73E8, 类 Google 蓝) + 微妙阴影。

**理由**：浅色简洁风是用户明确要求，QSS 实现无第三方依赖。

## Capabilities

### New Capabilities

- `gui-search`：桌面客户端搜索功能，包含单文件浏览搜索和目录跨文件搜索两种模式，支持精确/模糊匹配、分页展示、一键导出。

### Modified Capabilities

- 无。`excelops` library 零改动。

## Risks / Trade-offs

| 风险 | 处置 |
|---|---|
| **PySide6 安装**：Windows/macOS 有 wheel，Linux 需系统库 | pyproject.toml 锁定 `pyside6>=6.6,<6.7`，启动时检测可用性，不可用优雅降级 |
| **大文件内存**：`read_sheet` 返回全量 rows，百万行可能数百 MB | 文件大小预检（>500MB 提示），接受全量加载 tradeoff |
| **搜索无法真正取消** | 首期接受限制，UI 层禁用重复触发，标记 Phase 1.5 改进 |
| **Signal 类型安全**：跨线程传递 SheetData | 明确声明 `Signal(SheetData)`，避免跨线程传 QWidget |
| **测试与 PySide6 依赖**：GUI 测试需 PySide6 | 用 `pytest.importorskip("pyside6")` 标记，未安装时 skip |

## Migration Plan

纯新增，无破坏性改动：
1. 新增 `excelOps/src/excelops_gui/` 包（所有 GUI 代码）
2. 更新 `excelOps/pyproject.toml`：添加 `gui` extra + 包发现配置
3. 新增 `excelOps/tests/test_gui/` 测试目录（PySide6 skip 策略）

**回滚**：删除 `excelops_gui/` 包和 pyproject.toml 中 `gui` extra，不影响 library。