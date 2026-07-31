"""xlsxwriter-based writer with Copy-on-Write (design D5 / D9).

Writes a brand-new workbook (never modifies an existing one) via a same-dir
temp file, flushed + fsynced, then atomically ``os.replace``-d onto the target.
An interrupted or failed write can never corrupt an existing target — the temp
file is the only thing that can be left half-written, and it is cleaned up on
every failure path.

xlsxwriter serializes to an in-memory buffer first; that buffer is what gets
written through the temp-file fd and fsynced before the atomic replace. Date
cells are written with an explicit number format so their type survives a
read -> write -> read round-trip (xlsxwriter otherwise stores a bare serial
number with no date formatting, which reads back as an int).
"""

from __future__ import annotations

import contextlib
import io
import os
import tempfile
import time
from datetime import date, datetime
from pathlib import Path

import xlsxwriter

from ..errors import FileLocked, WriteError
from .models import SheetData, WriteResult

__all__ = ["write_workbook"]

_REPLACE_RETRIES = 2  # extra attempts after the first
_REPLACE_BACKOFF = 0.15  # seconds between retries (Windows target-in-use backoff)


def _build_bytes(sheets: dict[str, SheetData]) -> bytes:
    """Render the workbook into an in-memory xlsx byte string."""
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True})
    date_fmt = wb.add_format({"num_format": "yyyy-mm-dd"})
    datetime_fmt = wb.add_format({"num_format": "yyyy-mm-dd hh:mm:ss"})
    try:
        for name, sd in sheets.items():
            ws = wb.add_worksheet(name)
            ws.write_row(0, 0, list(sd.columns))
            for r, row in enumerate(sd.rows, start=1):
                for c, val in enumerate(row):
                    # write_datetime stores the value WITH a date number format,
                    # so openpyxl reads it back as a date (not a bare serial).
                    if isinstance(val, datetime):
                        ws.write_datetime(r, c, val, datetime_fmt)
                    elif isinstance(val, date):
                        ws.write_datetime(
                            r, c, datetime(val.year, val.month, val.day), date_fmt
                        )
                    else:
                        ws.write(r, c, val)
        wb.close()
    except Exception as e:  # xlsxwriter raises on bad sheet names / input
        with contextlib.suppress(Exception):
            wb.close()
        raise WriteError(f"failed to render workbook: {e}") from e
    return buf.getvalue()


def _atomic_replace(tmp_path: Path, target: Path) -> None:
    """Atomically move tmp onto target, retrying transient PermissionError.

    A persistent lock (e.g. target open in Excel on Windows) surfaces as
    ``FileLocked``; other OS errors become ``WriteError``. Never raises a bare
    ``PermissionError``.
    """
    last_err: Exception | None = None
    for attempt in range(_REPLACE_RETRIES + 1):
        try:
            os.replace(tmp_path, target)
            return
        except PermissionError as e:
            last_err = e
            if attempt < _REPLACE_RETRIES:
                time.sleep(_REPLACE_BACKOFF)
            continue
        except OSError as e:
            raise WriteError(f"failed to replace {target}: {e}") from e
    raise FileLocked(f"target is locked (open in another app?): {target}") from last_err


def _safe_unlink(p: Path) -> None:
    try:
        p.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def write_workbook(
    path: str | Path,
    sheets: dict[str, SheetData],
    source_ref: str | None = None,
) -> WriteResult:
    """Write ``sheets`` (name -> SheetData) as a new xlsx workbook at ``path``.

    Uses Copy-on-Write: an existing target is never corrupted by a failed
    write. Empty ``rows`` write a header-only sheet; empty ``columns`` or ragged
    rows raise ``WriteError``. Returns a structured ``WriteResult``; the input
    SheetData objects are never mutated.
    """
    target = Path(path)
    parent = target.parent
    if not parent.exists():
        raise WriteError(f"parent directory does not exist: {parent}")
    if not sheets:
        raise WriteError("no sheets to write")
    for name, sd in sheets.items():
        if not isinstance(sd, SheetData):
            raise WriteError(f"invalid SheetData for sheet {name!r}")
        if len(sd.columns) == 0:
            raise WriteError(f"sheet {name!r} has no columns")
        if any(len(row) != len(sd.columns) for row in sd.rows):
            raise WriteError(
                f"sheet {name!r} has a row whose length != column count"
            )

    data = _build_bytes(sheets)
    rows_written = sum(len(sd.rows) for sd in sheets.values())

    # 1) same-dir (same-volume) temp file so os.replace stays atomic
    try:
        fd, tmp_name = tempfile.mkstemp(
            dir=parent, prefix=f".{target.name}.", suffix=".tmp"
        )
    except OSError as e:
        raise WriteError(f"could not create temp file in {parent}: {e}") from e

    tmp_path = Path(tmp_name)
    try:
        # 2-3) write -> flush -> fsync -> close (durability before replace).
        # A disk/quota failure here MUST surface as WriteError, not a bare OSError.
        with os.fdopen(fd, "wb") as f:
            try:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            except OSError as e:
                raise WriteError(f"failed to persist temp file: {e}") from e
        # 4) atomic replace (with short retry for a locked target)
        _atomic_replace(tmp_path, target)
    except BaseException:
        # any failure path: clean the temp file, leave existing target intact
        _safe_unlink(tmp_path)
        raise

    # 5) return structured result
    return WriteResult(
        path=target,
        bytes_written=len(data),
        rows_written=rows_written,
        source_ref=source_ref,
    )
