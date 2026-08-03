"""Tests for excelops.backends.merger — the Excel merge engine.

TDD test suite written before implementation. All tests should FAIL
until merger.py, MergeError, and MergeResult exist.
"""

from __future__ import annotations

from datetime import date

import pytest
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from excelops.backends.merger import merge_workbook
from excelops.backends.models import MergeResult
from excelops.errors import MergeError

# ---------------------------------------------------------------------------
# Helpers — build fixture workbooks on the fly
# ---------------------------------------------------------------------------


def _make_wb(tmp_path, sheets: dict[str, list[list]], name: str = "file.xlsx",
             col_widths: dict[str, float] | None = None,
             header_style: bool = False,
             merge_cells: list[tuple[int, int, int, int]] | None = None):
    """Build an xlsx workbook.

    sheets: {"sheet_name": [[col_headers], [row1], [row2], ...]}
    col_widths: {"A": 20, "B": 30} — applied to every sheet
    header_style: if True, make row 1 bold + blue fill
    merge_cells: list of (min_row, min_col, max_row, max_col) 1-indexed
    """
    p = tmp_path / name
    wb = Workbook()
    for i, (sname, data) in enumerate(sheets.items()):
        if i == 0:
            ws = wb.active
            ws.title = sname
        else:
            ws = wb.create_sheet(sname)
        for row in data:
            ws.append(list(row))
        if col_widths:
            for col_letter, width in col_widths.items():
                ws.column_dimensions[col_letter].width = width
        if header_style and len(data) > 0:
            for cell in ws[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill(start_color="0000FF", end_color="0000FF", fill_type="solid")
        if merge_cells:
            for mr1, mc1, mr2, mc2 in merge_cells:
                ws.merge_cells(start_row=mr1, start_column=mc1, end_row=mr2, end_column=mc2)
    wb.save(p)
    return p


# ---------------------------------------------------------------------------
# 4.1 Two single-sheet files merge successfully
# ---------------------------------------------------------------------------


class TestBasicMerge:
    def test_single_sheet_row_count(self, tmp_path):
        """Merged row count == a rows + b rows (excluding header)."""
        a = _make_wb(tmp_path, {"data": [["id", "name"], [1, "a"], [2, "b"]]}, "a.xlsx")
        b = _make_wb(tmp_path, {"data": [["id", "name"], [3, "c"], [4, "d"], [5, "e"]]}, "b.xlsx")
        out = tmp_path / "out.xlsx"

        result = merge_workbook(a, b, out)

        assert isinstance(result, MergeResult)
        assert result.rows_written == 5  # 2 + 3

        from openpyxl import load_workbook
        wb = load_workbook(out)
        ws = wb["data"]
        rows = list(ws.iter_rows(values_only=True))
        assert rows[0] == ("id", "name")
        assert rows[1] == (1, "a")
        assert rows[2] == (2, "b")
        assert rows[3] == (3, "c")
        assert rows[4] == (4, "d")
        assert rows[5] == (5, "e")


# ---------------------------------------------------------------------------
# 4.2 Multi-sheet pairing by name
# ---------------------------------------------------------------------------


class TestMultiSheet:
    def test_sheets_pair_by_name(self, tmp_path):
        """Sheets present in both are merged; sheets in one are kept as-is."""
        a = _make_wb(tmp_path, {
            "orders": [["id", "amt"], [1, 10]],
            "summary": [["total"], [100]],
        }, "a.xlsx")
        b = _make_wb(tmp_path, {
            "orders": [["id", "amt"], [2, 20]],
            "meta": [["k"], ["v"]],
        }, "b.xlsx")
        out = tmp_path / "out.xlsx"

        merge_workbook(a, b, out)

        from openpyxl import load_workbook
        wb = load_workbook(out)
        assert set(wb.sheetnames) == {"orders", "summary", "meta"}

        orders_rows = list(wb["orders"].iter_rows(values_only=True))
        assert len(orders_rows) == 3  # header + 1 from a + 1 from b

        summary_rows = list(wb["summary"].iter_rows(values_only=True))
        assert len(summary_rows) == 2  # header + 1 (from a only)

        meta_rows = list(wb["meta"].iter_rows(values_only=True))
        assert len(meta_rows) == 2  # header + 1 (from b only)


# ---------------------------------------------------------------------------
# 4.3 Union column alignment
# ---------------------------------------------------------------------------


class TestColumnAlignment:
    def test_b_has_extra_column(self, tmp_path):
        a = _make_wb(tmp_path, {"s": [["id", "name"], [1, "a"]]}, "a.xlsx")
        b = _make_wb(tmp_path, {"s": [["id", "name", "remark"], [2, "b", "note"]]}, "b.xlsx")
        out = tmp_path / "out.xlsx"

        merge_workbook(a, b, out)

        from openpyxl import load_workbook
        ws = load_workbook(out)["s"]
        rows = list(ws.iter_rows(values_only=True))
        assert rows[0] == ("id", "name", "remark")
        assert rows[1] == (1, "a", None)   # a's row filled with None
        assert rows[2] == (2, "b", "note")

    def test_a_has_extra_column(self, tmp_path):
        a = _make_wb(tmp_path, {"s": [["id", "name", "tag"], [1, "a", "x"]]}, "a.xlsx")
        b = _make_wb(tmp_path, {"s": [["id", "name"], [2, "b"]]}, "b.xlsx")
        out = tmp_path / "out.xlsx"

        merge_workbook(a, b, out)

        from openpyxl import load_workbook
        ws = load_workbook(out)["s"]
        rows = list(ws.iter_rows(values_only=True))
        assert rows[0] == ("id", "name", "tag")
        assert rows[1] == (1, "a", "x")
        assert rows[2] == (2, "b", None)   # b's row filled with None

    def test_different_column_order(self, tmp_path):
        a = _make_wb(tmp_path, {"s": [["id", "name"], [1, "a"]]}, "a.xlsx")
        b = _make_wb(tmp_path, {"s": [["name", "id"], [2, "b"]]}, "b.xlsx")
        out = tmp_path / "out.xlsx"

        merge_workbook(a, b, out)

        from openpyxl import load_workbook
        ws = load_workbook(out)["s"]
        rows = list(ws.iter_rows(values_only=True))
        assert rows[0] == ("id", "name")   # a's order wins
        assert rows[1] == (1, "a")
        # b's row should map by column name
        assert rows[2][0] == "b"  # name column
        assert rows[2][1] == 2    # id column

    def test_identical_columns_direct_append(self, tmp_path):
        a = _make_wb(tmp_path, {"s": [["x", "y"], [1, 2]]}, "a.xlsx")
        b = _make_wb(tmp_path, {"s": [["x", "y"], [3, 4]]}, "b.xlsx")
        out = tmp_path / "out.xlsx"

        merge_workbook(a, b, out)

        from openpyxl import load_workbook
        ws = load_workbook(out)["s"]
        rows = list(ws.iter_rows(values_only=True))
        assert rows == [("x", "y"), (1, 2), (3, 4)]


# ---------------------------------------------------------------------------
# 4.4 No dedup
# ---------------------------------------------------------------------------


class TestNoDedup:
    def test_duplicate_rows_preserved(self, tmp_path):
        a = _make_wb(tmp_path, {"s": [["v"], [1], [1]]}, "a.xlsx")
        b = _make_wb(tmp_path, {"s": [["v"], [1]]}, "b.xlsx")
        out = tmp_path / "out.xlsx"

        result = merge_workbook(a, b, out)

        assert result.rows_written == 3  # all three 1's preserved


# ---------------------------------------------------------------------------
# 4.5 Format preservation
# ---------------------------------------------------------------------------


class TestFormatPreservation:
    def test_column_widths_preserved(self, tmp_path):
        a = _make_wb(tmp_path, {"s": [["id", "name"]]},
                     "a.xlsx", col_widths={"A": 25.0, "B": 40.0})
        b = _make_wb(tmp_path, {"s": [["id", "name"], [1, "a"]]}, "b.xlsx")
        out = tmp_path / "out.xlsx"

        merge_workbook(a, b, out)

        from openpyxl import load_workbook
        ws = load_workbook(out)["s"]
        assert ws.column_dimensions["A"].width == 25.0
        assert ws.column_dimensions["B"].width == 40.0

    def test_header_style_preserved(self, tmp_path):
        a = _make_wb(tmp_path, {"s": [["id", "name"]]}, "a.xlsx", header_style=True)
        b = _make_wb(tmp_path, {"s": [["id", "name"], [1, "a"]]}, "b.xlsx")
        out = tmp_path / "out.xlsx"

        merge_workbook(a, b, out)

        from openpyxl import load_workbook
        ws = load_workbook(out)["s"]
        h1 = ws.cell(row=1, column=1)
        assert h1.font.bold is True
        assert h1.fill.start_color.rgb is not None

    def test_merged_cells_preserved(self, tmp_path):
        # Two-column sheet with A1:B1 merged header
        a = _make_wb(tmp_path, {"s": [["title", "x"], ["data", "y"]]}, "a.xlsx",
                     merge_cells=[(1, 1, 1, 2)])  # merge A1:B1
        b = _make_wb(tmp_path, {"s": [["title", "x"], ["extra", "z"]]}, "b.xlsx")
        out = tmp_path / "out.xlsx"

        merge_workbook(a, b, out)

        from openpyxl import load_workbook
        ws = load_workbook(out)["s"]
        # The merged range should still exist
        merged_ranges = list(ws.merged_cells.ranges)
        assert any(str(r) == "A1:B1" for r in merged_ranges)


# ---------------------------------------------------------------------------
# 4.6 Type fidelity
# ---------------------------------------------------------------------------


class TestTypeFidelity:
    def test_date_preserved(self, tmp_path):
        a = _make_wb(tmp_path, {"s": [["id", "d"]]}, "a.xlsx")
        b = _make_wb(tmp_path, {"s": [["id", "d"], [1, date(2026, 3, 15)]]}, "b.xlsx")
        out = tmp_path / "out.xlsx"

        merge_workbook(a, b, out)

        from openpyxl import load_workbook
        ws = load_workbook(out)["s"]
        val = ws.cell(row=2, column=2).value
        assert isinstance(val, date)

    def test_none_preserved(self, tmp_path):
        a = _make_wb(tmp_path, {"s": [["id", "name"], [1, "a"]]}, "a.xlsx")
        b = _make_wb(tmp_path, {"s": [["id", "name", "tag"], [2, "b", "x"]]}, "b.xlsx")
        out = tmp_path / "out.xlsx"

        merge_workbook(a, b, out)

        from openpyxl import load_workbook
        ws = load_workbook(out)["s"]
        val = ws.cell(row=2, column=3).value  # a's row, tag column
        assert val is None

    def test_float_precision(self, tmp_path):
        a = _make_wb(tmp_path, {"s": [["v"]]}, "a.xlsx")
        b = _make_wb(tmp_path, {"s": [["v"], [3.14159]]}, "b.xlsx")
        out = tmp_path / "out.xlsx"

        merge_workbook(a, b, out)

        from openpyxl import load_workbook
        ws = load_workbook(out)["s"]
        val = ws.cell(row=2, column=1).value
        assert isinstance(val, float)
        assert abs(val - 3.14159) < 1e-10


# ---------------------------------------------------------------------------
# 4.7 Source files not modified
# ---------------------------------------------------------------------------


class TestSourceUnmodified:
    def test_source_files_unchanged(self, tmp_path):
        a = _make_wb(tmp_path, {"s": [["id"], [1]]}, "a.xlsx")
        b = _make_wb(tmp_path, {"s": [["id"], [2]]}, "b.xlsx")
        a_bytes = a.read_bytes()
        b_bytes = b.read_bytes()
        out = tmp_path / "out.xlsx"

        merge_workbook(a, b, out)

        assert a.read_bytes() == a_bytes
        assert b.read_bytes() == b_bytes


# ---------------------------------------------------------------------------
# 4.8 Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_path_a_not_found(self, tmp_path):
        a = tmp_path / "nonexistent.xlsx"
        b = _make_wb(tmp_path, {"s": [["id"]]}, "b.xlsx")
        out = tmp_path / "out.xlsx"

        with pytest.raises(MergeError, match="source file not found"):
            merge_workbook(a, b, out)

    def test_path_a_invalid_xlsx(self, tmp_path):
        a = tmp_path / "notxlsx.xlsx"
        a.write_text("this is not xlsx")
        b = _make_wb(tmp_path, {"s": [["id"]]}, "b.xlsx")
        out = tmp_path / "out.xlsx"

        with pytest.raises(MergeError, match="not a valid xlsx"):
            merge_workbook(a, b, out)

    def test_output_dir_missing(self, tmp_path):
        a = _make_wb(tmp_path, {"s": [["id"]]}, "a.xlsx")
        b = _make_wb(tmp_path, {"s": [["id"]]}, "b.xlsx")
        out = tmp_path / "no_such_dir" / "out.xlsx"

        with pytest.raises(MergeError, match="output directory does not exist"):
            merge_workbook(a, b, out)

    def test_out_path_same_as_source_raises(self, tmp_path):
        """out_path must not silently overwrite a source file."""
        a = _make_wb(tmp_path, {"s": [["id"], [1]]}, "a.xlsx")
        b = _make_wb(tmp_path, {"s": [["id"], [2]]}, "b.xlsx")

        with pytest.raises(MergeError, match="out_path must not be the same"):
            merge_workbook(a, b, a)  # out == path_a

        with pytest.raises(MergeError, match="out_path must not be the same"):
            merge_workbook(a, b, b)  # out == path_b


# ---------------------------------------------------------------------------
# 4.9 Return value
# ---------------------------------------------------------------------------


class TestReturnValue:
    def test_merge_result_fields(self, tmp_path):
        a = _make_wb(tmp_path, {"s1": [["id"], [1]], "s2": [["v"], [10]]}, "a.xlsx")
        b = _make_wb(tmp_path, {"s1": [["id"], [2]], "s2": [["v"], [20]]}, "b.xlsx")
        out = tmp_path / "out.xlsx"

        result = merge_workbook(a, b, out)

        assert result.path == out
        assert result.bytes_written > 0
        # s1: header + 1 (from a) + 1 (from b) = 2 data rows
        # s2: header + 1 (from a) + 1 (from b) = 2 data rows
        # total = 4
        assert result.rows_written == 4
        assert set(result.sheets) == {"s1", "s2"}
        assert out.exists()


# ---------------------------------------------------------------------------
# Union path format preservation (P1-2: Reviewer found gap)
# ---------------------------------------------------------------------------


class TestUnionPathFormatPreservation:
    """Format preservation when columns differ (union path triggers)."""

    def test_union_path_preserves_column_width(self, tmp_path):
        a = _make_wb(tmp_path, {"s": [["id", "name"], [1, "a"]]}, "a.xlsx",
                     col_widths={"A": 30.0})
        b = _make_wb(tmp_path, {"s": [["id", "name", "extra"], [2, "b", "x"]]}, "b.xlsx")
        out = tmp_path / "out.xlsx"

        merge_workbook(a, b, out)

        from openpyxl import load_workbook
        ws = load_workbook(out)["s"]
        assert ws.column_dimensions["A"].width == 30.0

    def test_union_path_preserves_header_style(self, tmp_path):
        a = _make_wb(tmp_path, {"s": [["id", "name"], [1, "a"]]}, "a.xlsx",
                     header_style=True)
        b = _make_wb(tmp_path, {"s": [["id", "name", "tag"], [2, "b", "x"]]}, "b.xlsx")
        out = tmp_path / "out.xlsx"

        merge_workbook(a, b, out)

        from openpyxl import load_workbook
        ws = load_workbook(out)["s"]
        h1 = ws.cell(row=1, column=1)
        assert h1.font.bold is True

    def test_union_path_recreates_header_merge(self, tmp_path):
        a = _make_wb(tmp_path, {"s": [["title", "x"], ["data", "y"]]}, "a.xlsx",
                     merge_cells=[(1, 1, 1, 2)])
        b = _make_wb(tmp_path, {"s": [["title", "x", "z"], ["a", "b", "c"]]}, "b.xlsx")
        out = tmp_path / "out.xlsx"

        merge_workbook(a, b, out)

        from openpyxl import load_workbook
        ws = load_workbook(out)["s"]
        merged_ranges = [str(r) for r in ws.merged_cells.ranges]
        assert "A1:B1" in merged_ranges
