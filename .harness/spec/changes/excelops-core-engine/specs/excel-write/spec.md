## ADDED Requirements

### Requirement: 写出新工作簿

write_workbook SHALL 将传入的若干 SheetData 写为一个全新的 xlsx 工作簿，每个 SheetData 对应一张工作表。写出 SHALL 使用 xlsxwriter（仅新建，不修改既有文件）。

#### Scenario: 多表写出

- **WHEN** 以 `{"汇总": sdA, "明细": sdB}` 调用 write_workbook
- **THEN** 生成的 xlsx 含名为 `汇总` 与 `明细` 的两张表，各自内容与 sdA/sdB 一致

### Requirement: Copy-on-Write 五步写契约

写出 SHALL 采用「同目录临时文件 + 原子替换」的五步契约，以保证既有目标与输入永不损坏：
1. 在目标文件**同目录**（同卷）创建临时文件（`tempfile.mkstemp(dir=target.parent)`），避免跨卷 `os.replace` 降级为拷贝；
2. 写入后 `flush` + `os.fsync` 再 `close`，保证内容落盘后再替换；
3. 以 `os.replace` 原子替换目标（跨平台，Windows 走 `MoveFileEx`）；
4. 任何失败路径 SHALL 清理临时文件，不留残留；
5. 成功后返回最终路径。

#### Scenario: 写出失败不破坏既有目标

- **WHEN** 目标路径已存在旧内容，且在写出过程中注入失败（如写入异常）
- **THEN** 既有目标文件内容保持不变，目标同目录下无 `.tmp` 残留

#### Scenario: 成功写出无残留

- **WHEN** write_workbook 成功完成
- **THEN** 目标文件存在且内容正确，目标同目录下不存在残留临时文件

### Requirement: 目标被占用映射为 FileLocked

当 `os.replace` 因目标被占用（Windows `PermissionError` / WinError 5）失败时，SHALL 在短重试（1-2 次，退避）后抛出 `FileLocked`，SHALL NOT 抛裸 `PermissionError`。

#### Scenario: 目标被 Excel 占用

- **WHEN** 目标 xlsx 正被 Excel 打开，调用 write_workbook
- **THEN** 抛出 `FileLocked`（而非 `PermissionError`），且临时文件已被清理

### Requirement: 结构化写结果且不污染输入

write_workbook SHALL 返回结构化结果（至少含最终路径、写入字节数、写入行数），SHALL NOT 仅返回路径或 `None`。write_workbook SHALL NOT 就地修改传入的 SheetData。

#### Scenario: 返回结构化结果且不污染输入

- **WHEN** 调用 write_workbook 后检查返回值与传入 SheetData
- **THEN** 返回值含 path/bytes/rows 字段；传入 SheetData 的 rows 与调用前逐一致

### Requirement: 写出数据可回读保真

write_workbook 写出的数据 SHALL 可被 read 能力原样读回（列名与单元格值一致）。

#### Scenario: 写后读往返

- **WHEN** 写出 SheetData 后用 read_sheet 读回同一张表
- **THEN** 读回的 SheetData.columns 与原一致，rows 与原逐单元格相等

### Requirement: 写入错误的类型化异常

不可写路径（如父目录不存在）或无效 SheetData（如列名为空）SHALL 抛出 `WriteError`，SHALL NOT 透传裸库异常。

#### Scenario: 父目录不存在

- **WHEN** 目标路径的父目录不存在时调用 write_workbook
- **THEN** 抛出 `WriteError`
