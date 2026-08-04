## Why

excelOps Phase 1 已打通 `read → analyze → write` 骨干，但用户在实际业务场景中需要的不是单步读写，而是**多张报表的组合变换**：合并同类表、按编码查找价格、核算保质期、按列投影、生成文字说明、多表转换合成采购/销售报表。当前这些逻辑散落在用户自己的脚本里，重复、易错、无法复用。本次变更在 `backends/` 之上新增一个纯函数式的业务操作层 `ops/`，把这些高频模式沉淀为可组合、可测试的原语与配方。

## What Changes

- **新增 `excelops/ops/` 模块**：纯函数式业务操作层，零 I/O、零副作用，输入输出均为 `SheetData`。
- **新增 `ops/primitives.py`**：5 个共用原语（`project`、`union`、`lookup`、`derive`、`narrate`），是整个操作层的地基。
- **新增 6 个配方模块**：`combine`（多表合并）、`lookup`（多级查找）、`shelf_life`（保质期计算）、`project`（列投影）、`narrate`（统计文字说明）、`transform`（多表转换合成）。
- **新增错误类型**：`LookupError`、`TransformError` 等，挂入现有 `errors.py` 异常树。
- **扩展 `__init__.py`**：导出 `ops` 层公共面。
- **新增测试**：每个原语和配方的单元测试 + 跨能力集成测试。

**BREAKING**：无。`ops/` 是纯新增，不修改任何现有 `backends/` 接口。

## Capabilities

### New Capabilities

- `report-combine`：多张同类报表纵向合并（UNION ALL），支持用户指定列顺序；格式不一致时按列名对齐，缺失列填 None。
- `product-lookup`：按编码/商品条码/商品名称的优先级 fallback 查找价格表，带回指定列；未匹配行可配置为留空或标记。
- `shelf-life`：根据生产日期 + 保质期（天/月/年），计算是否超过可配置的保质期分数（1/3、1/2 或任意 N）。
- `column-project`：从表中选取指定列（可配置），支持重命名映射和重排序。
- `stats-narrate`：根据统计结果按模板生成说明文字（列名 + 核算结果的自由组合）。
- `table-transform`：多表按转换关系（字段映射、计算公式、单位换算、聚合、条件分支）自动合成目标表（采购需求表 / 销售完成情况表）。

### Modified Capabilities

- 无。本变更不修改任何已有规格的需求层。

## Impact

- **代码**：新增 `excelops/ops/` 目录（~7 个模块），扩展 `excelops/__init__.py`，扩展 `excelops/errors.py`。
- **依赖**：ops 层仅依赖现有 `backends.models.SheetData` 和标准库，**不引入新依赖**，**不强制 `[duckdb]` extra**。
- **测试**：新增 `tests/ops/` 测试目录，覆盖所有原语与配方。
- **兼容性**：完全向后兼容，现有用户零改动。
