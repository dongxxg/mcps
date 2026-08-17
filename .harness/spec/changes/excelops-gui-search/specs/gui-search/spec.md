## ADDED Requirements

### Requirement: 桌面客户端启动与包结构

系统 SHALL 提供 `excelops_gui` 包，可通过 `python -m excelops_gui` 启动桌面客户端。

系统 SHALL 将 `excelops_gui` 声明为 `excelops` 的可选 extra（`pip install 'excelops[gui]'`），`pip install excelops` 不安装任何 GUI 依赖。

系统 SHALL 将 GUI 依赖锁定为 `pyside6>=6.6,<6.7`。

#### Scenario: 启动客户端
- **WHEN** 用户运行 `python -m excelops_gui`
- **THEN** 显示 MainWindow，无命令行参数即可启动

#### Scenario: PySide6 未安装
- **WHEN** 用户运行 `python -m excelops_gui` 但未安装 PySide6
- **THEN** 打印安装指引（`pip install 'excelops[gui]'`），不 crash 到堆栈

#### Scenario: 纯 library 安装无 GUI
- **WHEN** 用户执行 `pip install excelops`
- **THEN** 安装成功，不包含 PySide6，`import excelops` 正常工作

### Requirement: 三区布局 MainWindow

系统 SHALL 提供三区布局的 `QMainWindow`：左侧文件/Sheet 导航区、中间数据展示区、右侧操作面板区。

#### Scenario: 三区同时可见
- **WHEN** 客户端启动
- **THEN** 左侧导航区、中间数据区、右侧操作面板同时可见，通过 `QSplitter` 可拖拽调整宽度

#### Scenario: 顶部工具栏
- **WHEN** 客户端启动
- **THEN** 顶部显示工具栏，包含：打开文件、打开目录、当前文件标签、导出按钮、状态标签

### Requirement: 文件/Sheet 导航

系统 SHALL 在左侧提供文件/Sheet 树形导航，用户可打开 `.xlsx` 文件并切换工作表。

#### Scenario: 打开文件
- **WHEN** 用户点击"打开文件"并选择 `price.xlsx`
- **THEN** 树中显示该文件，展开后列出所有 sheet 名

#### Scenario: 切换 Sheet
- **WHEN** 用户点击某个 sheet
- **THEN** 中间数据区加载并显示该 sheet 的数据（分页显示）

#### Scenario: 打开非 xlsx 文件
- **WHEN** 用户选择 `.csv` 或 `.txt` 文件
- **THEN** 显示错误提示，数据区不变

### Requirement: 数据展示分页

系统 SHALL 使用 `QTableView` + `PaginatedModel` 展示数据，默认 500 行/页。

#### Scenario: 数据超过一页
- **WHEN** 某 sheet 有 1250 行数据
- **THEN** 显示前 500 行，底部显示分页控件 `[首页][上一页] 1/3 [下一页][末页] 共 1250 行`

#### Scenario: 翻页
- **WHEN** 用户点击"下一页"
- **THEN** 显示第 501-1000 行，页码更新为 2/3

#### Scenario: 数据少于一页
- **WHEN** 某 sheet 有 30 行数据
- **THEN** 显示全部 30 行，分页控件显示 1/1

#### Scenario: 空 sheet
- **WHEN** 某 sheet 无数据行
- **THEN** 数据区显示"无数据"提示，分页控件隐藏

#### Scenario: 页大小常量
- **WHEN** 默认配置
- **THEN** 每页显示 500 行（由常量 `DEFAULT_PAGE_SIZE` 控制）

### Requirement: 操作面板切换

系统 SHALL 在右侧提供操作面板区，顶部有操作选择器（Tab），当前只有"搜索"操作可用。

#### Scenario: 搜索面板默认选中
- **WHEN** 客户端启动
- **THEN** "搜索"面板为当前选中面板，显示搜索参数输入区

#### Scenario: 面板注册可扩展
- **WHEN** 未来新增"过滤"操作面板
- **THEN** 通过 `@register_panel("filter")` 注册后，操作选择器自动出现"过滤"选项

### Requirement: 单文件浏览搜索

系统 SHALL 在搜索面板提供单文件浏览搜索模式：用户选择列、输入值、选择匹配模式，在当前 sheet 内过滤行。

#### Scenario: 精确匹配搜索
- **WHEN** 当前 sheet 有列 `编码`，用户选择列=`编码`，值=`A001`，模式=`精确`，点击搜索
- **THEN** 数据区显示 `编码=A001` 的行（分页展示），状态栏显示匹配行数

#### Scenario: 模糊匹配搜索
- **WHEN** 当前 sheet 有列 `名称`，用户选择列=`名称`，值=`牛奶`，模式=`模糊`，点击搜索
- **THEN** 数据区显示 `名称` 包含 `牛奶` 的所有行（不区分大小写）

#### Scenario: 搜索结果无匹配
- **WHEN** 搜索条件无匹配行
- **THEN** 数据区显示"无匹配结果"，状态栏显示 `0 行`

#### Scenario: 搜索后恢复
- **WHEN** 搜索后用户点击导航中的原始 sheet
- **THEN** 数据区恢复显示该 sheet 的全部数据（搜索只是覆盖当前视图，不修改 sheet 数据）

#### Scenario: 选择列列表
- **WHEN** 用户打开搜索面板
- **THEN** "列"下拉框包含当前 sheet 的所有列名

#### Scenario: 当前无打开文件时搜索
- **WHEN** 未打开任何文件时点击搜索
- **THEN** 显示提示"请先打开一个文件"，不执行搜索

### Requirement: 目录跨文件搜索

系统 SHALL 在搜索面板提供目录跨文件搜索模式：用户选择目录、添加条件（字段/值/模式），跨目录内所有 `.xlsx` 文件搜索。

#### Scenario: 选择目录并搜索
- **WHEN** 用户点击"选择目录"选择 `C:\data\`，添加条件 `编码=A001`，点击搜索
- **THEN** 数据区显示所有包含 `编码=A001` 的行，附带 `__file__`、`__sheet__`、`__match_field__` 溯源列

#### Scenario: 多条件优先级搜索
- **WHEN** 用户添加两个条件：`编码=A001`（精确）和 `名称=牛奶`（模糊）
- **THEN** 先按编码精确匹配，未命中的行再按名称模糊匹配（first-hit-wins）

#### Scenario: 添加/删除条件行
- **WHEN** 用户点击"添加条件"
- **THEN** 增加一行条件输入（字段下拉 + 值输入 + 模式选择 + 删除按钮）

#### Scenario: 目录无 xlsx 文件
- **WHEN** 选择的目录内无 `.xlsx` 文件
- **THEN** 显示错误提示"目录内无 .xlsx 文件"

#### Scenario: 目录跨文件搜索无匹配
- **WHEN** 搜索条件在所有文件中均无匹配
- **THEN** 数据区显示"无匹配结果"，不报错

### Requirement: 搜索后台线程执行

系统 SHALL 在后台线程执行搜索操作，搜索期间 UI 不冻结。

#### Scenario: 大文件搜索不阻塞 UI
- **WHEN** 用户搜索一个大文件（>10000 行）
- **THEN** 搜索期间工具栏搜索按钮被禁用，状态栏显示"搜索中..."，搜索完成后自动恢复

#### Scenario: 搜索错误处理
- **WHEN** 搜索过程中发生异常（如文件损坏）
- **THEN** 状态栏显示错误消息，搜索按钮恢复可用

### Requirement: 一键导出

系统 SHALL 提供一键导出功能，将当前数据区显示的结果导出为新 `.xlsx` 文件。

#### Scenario: 导出搜索结果
- **WHEN** 搜索完成后用户点击"导出"
- **THEN** 弹出文件保存对话框，用户选择路径后生成 `.xlsx` 文件

#### Scenario: 导出原始数据
- **WHEN** 未搜索时（显示原始 sheet 数据）用户点击"导出"
- **THEN** 导出当前 sheet 的全部数据到新 `.xlsx`

#### Scenario: 导出后台执行
- **WHEN** 导出大量数据（>50000 行）
- **THEN** 导出在后台线程执行，状态栏显示"导出中..."，完成后显示"导出完成: X 行"

#### Scenario: 导出取消
- **WHEN** 用户在保存对话框点击取消
- **THEN** 不生成文件，状态栏不变

### Requirement: 浅色简洁风主题

系统 SHALL 应用浅色简洁风 QSS 主题（`light.qss`）。

#### Scenario: 主题应用
- **WHEN** 客户端启动
- **THEN** 所有控件应用浅色主题：白底、浅灰分区、细边框、主色 #1A73E8

### Requirement: 零业务逻辑

系统 SHALL 在 GUI 层不实现任何搜索算法或数据转换逻辑，只调用 `excelops` library 公开 API。

#### Scenario: 搜索实现
- **WHEN** 执行搜索
- **THEN** GUI 层调用 `search_files()`（目录模式）或 `read_sheet()` + `ops.filter()`（单文件模式），不自行实现匹配逻辑

#### Scenario: 数据展示
- **WHEN** 展示搜索结果
- **THEN** GUI 层将 `SheetData` 转换为 Qt 模型可消费的格式，不修改 `SheetData` 内容