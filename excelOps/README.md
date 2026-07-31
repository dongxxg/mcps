# excelOps

Pure-Python library for reading, analyzing, and writing Excel `.xlsx` workbooks.

A thin end-to-end capability layer: **read** (openpyxl) → **analyze** (embedded
DuckDB) → **write** (xlsxwriter), glued by a single shared `SheetData` type.
No pandas required.

## Install

```bash
pip install -e excelOps                 # core read/write (pure Python)
pip install -e 'excelOps[duckdb]'       # + analyze engine (DuckDB + pyarrow)
```

## Why

Excel round-trips silently drop formulas/formats/types, and a write interruption
corrupts the whole workbook. excelOps handles both at the architecture layer:

- **Copy-on-Write** writes (same-dir temp file + atomic `os.replace`) — an
  existing target is never corrupted by a failed write.
- **Type fidelity** — dates stay dates, no implicit stringification across the
  read → analyze → write loop.
- **Schema discipline in the reader** — header normalization (None/duplicate
  names → unique placeholders) and ragged-row padding, so downstream analyze
  and write always see well-formed `SheetData`.

Backends are **policy-unaware** (no safety/audit coupling) — Phase 2 will wrap
them as MCP tools.
