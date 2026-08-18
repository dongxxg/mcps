"""Command-line entry point for the excelOps desktop client.

Usage::

    python -m excelops_gui

Gracefully reports install instructions when PySide6 is missing rather than
crashing into a stack trace.
"""

from __future__ import annotations

import sys


def _ensure_pyside6() -> None:
    try:
        import PySide6  # noqa: F401  - verify install, raise below if missing
    except ImportError:
        print(
            "PySide6 is not installed. Install the GUI extra:\n"
            "    pip install 'excelops[gui]'",
            file=sys.stderr,
        )
        raise


def main() -> int:
    _ensure_pyside6()
    from PySide6.QtWidgets import QApplication  # type: ignore[import-untyped]

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    from .main_window import MainWindow
    from .theme import apply_theme

    apply_theme(app)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
