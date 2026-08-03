"""``transform_tables`` recipe — multi-table transformation into a target sheet.

Composes all primitives (:func:`project`, :func:`union`, :func:`lookup`,
:func:`derive`, :func:`filter`) and — for aggregation — the
:class:`~excelops.backends.analyzer.Analyzer` (optional ``[duckdb]`` extra).

A rule is a ``dict`` with a ``"kind"`` field:

| kind | keys | meaning |
|------|------|---------|
| ``map`` | ``source``, ``target`` | copy/rename a column |
| ``expr`` | ``target``, ``expr`` | arithmetic formula over column names |
| ``factor`` | ``source``, ``target``, ``factor`` | multiply a column by a constant |
| ``when`` | ``target``, ``condition``, ``then``, ``else`` | conditional branch |
| ``aggregate`` | ``group_by``, ``aggregations`` | GROUP BY (uses Analyzer) |

``tables`` is a ``dict[alias -> SheetData]`` so rules can reference columns as
``"alias.col"``.
"""

from __future__ import annotations

import ast
import operator
from typing import Any

from ..backends.models import SheetData
from ..errors import TransformError
from .derive import derive

__all__ = ["transform_tables"]

# Supported binary operators for the expression evaluator.
_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_CMP_OPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}
def transform_tables(
    tables: dict[str, SheetData],
    rules: list[dict[str, Any]],
) -> SheetData:
    """Apply a sequence of transformation rules to produce a target sheet.

    Args:
        tables: Named input tables. Column references in rules use
            ``"alias.col"`` syntax.
        rules: Ordered list of transformation rule dicts (see table above).

    Returns:
        The transformed ``SheetData``.
    """
    # --- build the working sheet: union all inputs, prefixing columns by alias ---
    if not tables:
        raise TransformError("transform_tables requires at least one input table")

    # Start with the first table's data, then join/union the rest by column
    # alignment. For map/expr/factor/when we need a single wide sheet, so we
    # horizontal-join (column-union) the inputs first.
    working = _horizontal_join(tables)

    for rule in rules:
        kind = rule.get("kind")
        if kind == "map":
            working = _apply_map(working, rule)
        elif kind == "expr":
            working = _apply_expr(working, rule)
        elif kind == "factor":
            working = _apply_factor(working, rule)
        elif kind == "when":
            working = _apply_when(working, rule)
        elif kind == "aggregate":
            working = _apply_aggregate(working, rule)
        else:
            raise TransformError(f"unknown rule kind: {kind!r}")

    return working


def _horizontal_join(tables: dict[str, SheetData]) -> SheetData:
    """Column-union multiple tables. Requires equal row counts."""
    aliases = list(tables.keys())
    first = tables[aliases[0]]
    n = len(first.rows)
    for alias in aliases[1:]:
        if len(tables[alias].rows) != n:
            raise TransformError(
                f"cannot horizontal-join tables with different row counts: "
                f"{aliases[0]}={n} vs {alias}={len(tables[alias].rows)}"
            )

    columns_out = list(first.columns)
    # Build per-row dicts, then merge.
    row_dicts: list[dict[str, Any]] = [
        dict(zip(first.columns, row, strict=True)) for row in first.rows
    ]
    for alias in aliases[1:]:
        sd = tables[alias]
        for i, row in enumerate(sd.rows):
            for col, val in zip(sd.columns, row, strict=True):
                row_dicts[i][f"{alias}.{col}"] = val
        columns_out.extend(f"{alias}.{col}" for col in sd.columns)

    rows_out = tuple(tuple(d[c] for c in columns_out) for d in row_dicts)
    return SheetData(columns=tuple(columns_out), rows=rows_out)


def _apply_map(sd: SheetData, rule: dict[str, Any]) -> SheetData:
    src, tgt = rule["source"], rule["target"]
    if src not in sd.columns:
        raise TransformError(f"map source column not found: {src!r}")
    idx = sd.columns.index(src)
    rows = tuple(row[:idx] + row[idx + 1 :] + (row[idx],) for row in sd.rows)
    cols = sd.columns[:idx] + sd.columns[idx + 1 :] + (tgt,)
    return SheetData(columns=cols, rows=rows)


def _eval_expr(expr: str, row: dict[str, Any]) -> Any:
    """Safely evaluate an arithmetic expression over row values."""
    node = ast.parse(expr, mode="eval")

    def _ev(n: ast.AST) -> Any:
        if isinstance(n, ast.Expression):
            return _ev(n.body)
        if isinstance(n, ast.BinOp):
            left, right = _ev(n.left), _ev(n.right)
            op_type = type(n.op)
            if op_type not in _BIN_OPS:
                raise TransformError(f"unsupported operator: {op_type.__name__}")
            return _BIN_OPS[op_type](left, right)
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
            return -_ev(n.operand)
        if isinstance(n, ast.Name):
            if n.id in row:
                return row[n.id]
            raise TransformError(f"unknown column in expr: {n.id!r}")
        if isinstance(n, ast.Constant):
            return n.value
        raise TransformError(f"unsupported expression element: {type(n).__name__}")

    return _ev(node)


def _apply_expr(sd: SheetData, rule: dict[str, Any]) -> SheetData:
    return derive(sd, rule["target"], lambda r: _eval_expr(rule["expr"], r))


def _apply_factor(sd: SheetData, rule: dict[str, Any]) -> SheetData:
    src, tgt, factor = rule["source"], rule["target"], rule["factor"]
    return derive(sd, tgt, lambda r, _s=src, _f=factor: _num(r.get(_s)) * _f)


def _num(v: Any) -> float:
    if v is None:
        return 0.0
    return float(v)


def _eval_condition(cond: str, row: dict[str, Any]) -> bool:
    """Evaluate a comparison condition like 'a < b'."""
    node = ast.parse(cond, mode="eval")

    def _ev(n: ast.AST) -> Any:
        if isinstance(n, ast.Expression):
            return _ev(n.body)
        if isinstance(n, ast.Compare):
            left = _ev(n.left)
            for op, comparator in zip(n.ops, n.comparators, strict=True):
                right = _ev(comparator)
                op_type = type(op)
                if op_type not in _CMP_OPS:
                    raise TransformError(f"unsupported comparison: {op_type.__name__}")
                if not _CMP_OPS[op_type](left, right):
                    return False
                left = right
            return True
        if isinstance(n, ast.BoolOp):
            if isinstance(n.op, ast.And):
                return all(_ev(v) for v in n.values)
            if isinstance(n.op, ast.Or):
                return any(_ev(v) for v in n.values)
        if isinstance(n, ast.Name):
            if n.id in row:
                return row[n.id]
            raise TransformError(f"unknown column in condition: {n.id!r}")
        if isinstance(n, ast.Constant):
            return n.value
        if isinstance(n, ast.BinOp):
            left, right = _ev(n.left), _ev(n.right)
            return _BIN_OPS[type(n.op)](left, right)
        raise TransformError(f"unsupported condition element: {type(n).__name__}")

    return bool(_ev(node))


def _apply_when(sd: SheetData, rule: dict[str, Any]) -> SheetData:
    cond = rule["condition"]
    then_v = rule["then"]
    else_v = rule["else"]

    def _eval(row: dict[str, Any]) -> Any:
        return then_v if _eval_condition(cond, row) else else_v

    return derive(sd, rule["target"], _eval)


def _apply_aggregate(sd: SheetData, rule: dict[str, Any]) -> SheetData:
    """Aggregate via the DuckDB Analyzer (requires [duckdb] extra)."""
    try:
        from ..backends.analyzer import Analyzer
    except Exception as e:
        raise TransformError(
            "aggregate rule requires the [duckdb] extra: pip install excelops[duckdb]"
        ) from e

    group_by = rule["group_by"]
    aggregations = rule["aggregations"]  # {col: func}

    with Analyzer() as az:
        az.register("src", sd)
        agg_sql = ", ".join(
            f"{func}({col}) AS {col}_{func}" for col, func in aggregations.items()
        )
        sql = f"SELECT {group_by}, {agg_sql} FROM src GROUP BY {group_by}"
        return az.query(sql)
