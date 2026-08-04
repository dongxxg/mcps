## ADDED Requirements

### Requirement: 纵向合并两个 Excel 工作簿
系统 SHALL 接受两个 xlsx 文件路径和一个输出路径，将两个文件按 Sheet 名配对后纵向拼接数据行，写入一个全新的 xlsx 文件。源文件 A 和 B 均不被修改。

#### Scenario: 两个单 Sheet 文件成功合并
- **WHEN** file_a 和 file_b 各有一个同名 Sheet "data"，列头均为 `["id", "name"]`
- **THEN** 输出文件包含一个 "data" Sheet，列头 `["id", "name"]`，数据行为 file_a 所有行后接 file_b 所有行

#### Scenario: 多 Sheet 按名称配对
- **WHEN** file_a 有 Sheet `["orders", "summary"]`，file_b 有 Sheet `["orders", "meta"]`
- **THEN** 输出文件包含 Sheet `["orders", "summary", "meta"]`；"orders" 为两者合并，"summary" 和 "meta" 来自单个源

#### Scenario: 源文件不被修改
- **WHEN** 合并成功完成后
- **THEN** file_a 和 file_b 的字节内容与合并前完全一致

---

### Requirement: Union 列对齐（缺失填 None）
系统 SHALL 对两个 Sheet 的列头取并集。file_a 独有的列在 file_b 行中填充 None；file_b 独有的列在 file_a 行中填充 None。输出列顺序以 file_a 列顺序为准，file_b 的新列追加到末尾。

#### Scenario: file_b 多出列
- **WHEN** file_a 列头 `["id", "name"]`，file_b 列头 `["id", "name", "remark"]`
- **THEN** 输出列头 `["id", "name", "remark"]`；file_a 行第 3 列为 None；file_b 行第 3 列为实际值

#### Scenario: file_a 多出列
- **WHEN** file_a 列头 `["id", "name", "tag"]`，file_b 列头 `["id", "name"]`
- **THEN** 输出列头 `["id", "name", "tag"]`；file_b 行第 3 列为 None；file_a 行第 3 列为实际值

#### Scenario: 列顺序不同但名称相同
- **WHEN** file_a 列头 `["id", "name"]`，file_b 列头 `["name", "id"]`
- **THEN** 输出列头以 file_a 为准 `["id", "name"]`；file_b 行按列名映射到正确位置

#### Scenario: 列头完全相同
- **WHEN** 两文件列头完全一致（包括顺序）
- **THEN** 直接按位置拼接，无需重排

---

### Requirement: 不去重
系统 SHALL 保留两个源文件的所有数据行，不执行任何去重逻辑。

#### Scenario: 两文件有重复行
- **WHEN** file_a 第 2 行 `[1, "a"]` 与 file_b 第 3 行 `[1, "a"]` 完全相同
- **THEN** 输出文件中这两行均保留

#### Scenario: file_a 内部有重复行
- **WHEN** file_a 自身有重复行
- **THEN** 合并后这些重复行仍然保留

---

### Requirement: 保留 file_a 的视觉格式
系统 SHALL 完整保留 file_a 每个 Sheet 的以下视觉格式到输出文件：列宽、单元格样式（字体/颜色/边框/对齐）、合并单元格、行高。file_b 的数据行继承 file_a 对应列的样式。

#### Scenario: 列宽保留
- **WHEN** file_a "data" Sheet A 列宽 20、B 列宽 30
- **THEN** 输出文件 "data" Sheet A 列宽 20、B 列宽 30

#### Scenario: 单元格样式保留
- **WHEN** file_a 表头行字体加粗、背景色蓝色
- **THEN** 输出文件表头行保持相同样式

#### Scenario: 合并单元格保留
- **WHEN** file_a "summary" Sheet 有合并单元格 A1:B1
- **THEN** 输出文件 "summary" Sheet 保留该合并区域

#### Scenario: file_b 数据行继承列样式
- **WHEN** file_a A 列数字格式为 `#,##0.00`
- **THEN** 输出文件中来自 file_b 的 A 列数据行也应用 `#,##0.00` 格式

---

### Requirement: 类型保真
系统 SHALL 保持所有数据行的单元格类型与源文件一致（date / datetime / float / int / str / None）。

#### Scenario: date 类型保留
- **WHEN** file_a 某列为 Python `datetime.date` 值
- **THEN** 输出文件对应单元格为 Excel 日期类型（读回为 date 对象）

#### Scenario: None 类型保留
- **WHEN** 某单元格值为 `None`（含 union 填充的 None）
- **THEN** 输出文件对应单元格为空（读回为 `None`）

#### Scenario: float 精度保留
- **WHEN** file_b 某单元格为 `3.14159`
- **THEN** 输出文件对应单元格读回为 `3.14159`（float）

---

### Requirement: 错误处理
系统 SHALL 对以下错误条件抛出 `MergeError` 并附带清晰的错误信息。

#### Scenario: 源文件不存在
- **WHEN** `path_a` 指向不存在的文件
- **THEN** 抛出 `MergeError("source file not found: <path>")`

#### Scenario: 源文件不是有效 xlsx
- **WHEN** `path_a` 指向一个非 xlsx 文件（如 .txt）
- **THEN** 抛出 `MergeError("not a valid xlsx: <path>")`

#### Scenario: 输出目录不存在
- **WHEN** `out_path` 的父目录不存在
- **THEN** 抛出 `MergeError("output directory does not exist: <dir>")`

---

### Requirement: 返回结构化结果
系统 SHALL 返回 `MergeResult` 对象，包含输出路径、写入字节数、合并的总行数、参与合并的 Sheet 列表。

#### Scenario: 成功合并返回结果
- **WHEN** 两个文件各 10 行数据，合并成功
- **THEN** `MergeResult.path == out_path`，`MergeResult.rows_written == 20`，`MergeResult.sheets == ["data"]`
