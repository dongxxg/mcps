"""Thread workers — run long-running operations off the UI thread."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QThread, Signal  # type: ignore[import-untyped]


class BaseWorker(QThread):
    """Thread base class that emits typed signals for cross-thread communication.

    Subclasses override :meth:`run` and emit :attr:`progress` / :attr:`result`
    / :attr:`error` signals. The UI connects to those signals (Qt auto-queues
    across threads).
    """

    progress = Signal(int, str)  # percent, message
    result = Signal(object)
    error = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._cancelled = False

    def cancel(self) -> None:
        """Request the worker to stop. The :meth:`run` implementation must
        honour :attr:`is_cancelled` periodically."""
        self._cancelled = True

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled


class SearchWorker(BaseWorker):
    """Run a :class:`SearchPanel.execute` in a background thread."""

    def __init__(
        self,
        panel,  # SearchPanel instance (duck-typed)
        ctx: Any,
    ) -> None:
        super().__init__()
        self._panel = panel
        self._ctx = ctx

    def run(self) -> None:
        try:
            self.progress.emit(20, "搜索中...")
            if self.is_cancelled:
                return
            result = self._panel.execute(self._ctx)
            self.progress.emit(100, result.message or "完成")
            if result.error:
                self.error.emit(result.error)
            else:
                self.result.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))


class ExportWorker(BaseWorker):
    """Run ``export_to_xlsx`` in a background thread."""

    def __init__(
        self,
        sheet_data: Any,
        path: str,
        sheet_name: str = "Sheet1",
    ) -> None:
        super().__init__()
        self._sheet_data = sheet_data
        self._path = path
        self._sheet_name = sheet_name

    def run(self) -> None:
        try:
            from excelops_gui.exporter import export_to_xlsx

            self.progress.emit(30, "导出中...")
            write_result = export_to_xlsx(self._sheet_data, self._path, self._sheet_name)
            self.progress.emit(100, f"导出完成: {write_result.rows_written} 行")
            self.result.emit(write_result)
        except Exception as exc:
            self.error.emit(str(exc))


class LoadSheetWorker(BaseWorker):
    """Read a sheet into ``SheetData`` off the UI thread."""

    def __init__(self, file_path: str, sheet_name: str) -> None:
        super().__init__()
        self._file_path = file_path
        self._sheet_name = sheet_name

    def run(self) -> None:
        try:
            from excelops import read_sheet

            self.progress.emit(20, "加载数据...")
            sd = read_sheet(self._file_path, self._sheet_name)
            self.progress.emit(100, f"已加载 {len(sd.rows)} 行")
            self.result.emit(sd)
        except Exception as exc:
            self.error.emit(str(exc))
