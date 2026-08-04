## 1. 基础设施

- [x] 1.1 创建 `excelops/ops/` 目录结构（`__init__.py` + 各原语/配方模块空壳，含模块 docstring）
- [x] 1.2 在 `errors.py` 新增 `OpsError(ExcelOpsError)` 基类 + `CombineError` / `LookupError` / `ProjectError` / `TransformError` 子类，更新 `__init__.py` 导出

## 2. 共用原语（primitives）—— 地基

- [x] 2.1 实现 `ops/project.py`：`project(sd, columns, rename=None)` — 选列+重排+重命名，列不存在时抛 ProjectError
- [x] 2.2 实现 `ops/union.py`：`union(tables, column_order=None)` — 纵向堆叠对齐，空输入/列不存在时抛 CombineError
- [x] 2.3 实现 `ops/derive.py`：`derive(sd, name, fn)` — 行级派生列，fn 接收 dict（列名→值），返回新 SheetData
- [x] 2.4 实现 `ops/filter.py`：`filter(sd, predicate)` — 行级筛选，predicate 接收 dict 返回 bool
- [x] 2.5 实现 `ops/lookup.py`：`lookup(source, table, on, fetch, on_missing="null")` — 预建哈希索引 + 优先级 fallback + 列带回 + 未匹配策略
- [x] 2.6 实现 `ops/narrate.py`：`narrate(context, template)` — 基于 str.format 的模板渲染，支持数值格式化（:.2f / :,），缺失键保留占位符

## 3. 配方（recipes）—— 6 项业务能力

- [x] 3.1 实现 `ops/combine.py`：`combine_reports(reports, column_order=None)` — 多张表纵向合并（封装 union + project）
- [x] 3.2 实现 `ops/product_lookup.py`：`lookup_product(source, price_table, keys=None, fetch, on_missing="null")` — 编码→条码→名称多级查找（封装 lookup）
- [x] 3.3 实现 `ops/shelf_life.py`：`calc_shelf_life(sd, production_col, shelf_life_col, unit="day", fraction=1/3, reference_date=None, output_col="是否超保")` — 保质期分数计算（封装 derive）
- [x] 3.4 实现 `ops/column_project.py`：`project_columns(sd, columns, rename=None)` — 列投影（封装 project，语义别名）
- [x] 3.5 实现 `ops/stats_narrate.py`：`narrate_stats(sd, template)` — 批量统计文字说明（封装 narrate，逐行渲染）
- [x] 3.6 实现 `ops/transform.py`：`transform_tables(tables, rules)` — 多表按规则合成（组合 project/union/lookup/derive/filter + Analyzer 聚合）

## 4. 导出与集成

- [x] 4.1 更新 `excelops/ops/__init__.py`：导出所有原语和配方的公共面
- [x] 4.2 更新 `excelops/__init__.py`：导出 `ops` 层公共面（保持与现有导出风格一致）

## 5. 测试

- [x] 5.1 编写 `tests/ops/test_project.py`：覆盖选列、重排、重命名、列不存在报错、输入不变
- [x] 5.2 编写 `tests/ops/test_union.py`：覆盖一致/不一致列、column_order、空输入、单表、输入不变
- [x] 5.3 编写 `tests/ops/test_derive.py`：覆盖行级派生、fn 接收 dict、中文列名、空值
- [x] 5.4 编写 `tests/ops/test_filter.py`：覆盖行筛选、predicate 接收 dict、全留/全过滤
- [x] 5.5 编写 `tests/ops/test_lookup.py`：覆盖三级优先级、未匹配三种策略、重复键取首条、输入不变
- [x] 5.6 编写 `tests/ops/test_narrate.py`：覆盖单/多占位符、数值格式化、缺失键保留、批量渲染
- [x] 5.7 编写 `tests/ops/test_combine_recipe.py`：覆盖多表合并端到端
- [x] 5.8 编写 `tests/ops/test_product_lookup_recipe.py`：覆盖端到端查找
- [x] 5.9 编写 `tests/ops/test_shelf_life_recipe.py`：覆盖天/月/年单位、分数阈值、参考日期
- [x] 5.10 编写 `tests/ops/test_transform_recipe.py`：覆盖字段映射、公式、单位换算、条件分支、聚合（需 [duckdb]）

## 6. 验证

- [x] 6.1 运行全量测试 `pytest excelOps/tests/ops/ -v`，确保全部通过（覆盖率 ≥ 80%）
- [x] 6.2 运行 `ruff check excelOps/src/excelops/ops/` 确保零 error
- [x] 6.3 运行已有测试 `pytest excelOps/tests/` 确保无回归
