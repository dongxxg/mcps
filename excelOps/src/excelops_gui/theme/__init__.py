"""Light theme — minimal, Google Sheets / Notion-like QSS.

Palette:
    - background:      #FFFFFF
    - surface/panels:  #F5F5F5
    - borders:         #E0E0E0
    - primary/accent:  #1A73E8
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication  # type: ignore[import-untyped]

_LIGHT_QSS = r"""
QMainWindow {
    background-color: #FFFFFF;
}

QToolBar {
    background-color: #FAFAFA;
    border-bottom: 1px solid #E0E0E0;
    padding: 4px;
    spacing: 6px;
}

QPushButton {
    background-color: #FFFFFF;
    border: 1px solid #E0E0E0;
    border-radius: 4px;
    padding: 6px 12px;
    color: #333333;
}
QPushButton:hover {
    background-color: #E8F0FE;
    border-color: #1A73E8;
}
QPushButton:pressed {
    background-color: #D2E3FC;
}
QPushButton:disabled {
    background-color: #F5F5F5;
    color: #999999;
}
QPushButton#primary {
    background-color: #1A73E8;
    color: #FFFFFF;
    border-color: #1A73E8;
}
QPushButton#primary:hover {
    background-color: #1557B0;
}

QLineEdit {
    border: 1px solid #E0E0E0;
    border-radius: 4px;
    padding: 4px 6px;
    background-color: #FFFFFF;
}
QLineEdit:focus {
    border-color: #1A73E8;
}

QComboBox {
    border: 1px solid #E0E0E0;
    border-radius: 4px;
    padding: 4px 6px;
}

QTreeWidget {
    background-color: #FFFFFF;
    border: none;
    outline: none;
}
QTreeWidget::item {
    padding: 4px;
    border-bottom: 1px solid #F5F5F5;
}
QTreeWidget::item:selected {
    background-color: #E8F0FE;
    color: #1A73E8;
}

QHeaderView::section {
    background-color: #F5F5F5;
    border: 1px solid #E0E0E0;
    padding: 6px;
    font-weight: bold;
    color: #333333;
}

QTableWidget, QTableView {
    background-color: #FFFFFF;
    alternate-row-color: #FAFAFA;
    gridline-color: #E0E0E0;
    outline: none;
}
QTableWidget::item:selected, QTableView::item:selected {
    background-color: #E8F0FE;
    color: #1A73E8;
}

QTabWidget::pane {
    border: 1px solid #E0E0E0;
    border-top: none;
    background: #FFFFFF;
}
QTabBar::tab {
    background: #F5F5F5;
    border: 1px solid #E0E0E0;
    border-bottom: none;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    padding: 6px 14px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background: #FFFFFF;
    border-color: #1A73E8;
    color: #1A73E8;
    font-weight: bold;
}

QStatusBar {
    background-color: #FAFAFA;
    border-top: 1px solid #E0E0E0;
}

QSplitter::handle {
    background-color: #E0E0E0;
}
QSplitter::handle:horizontal {
    width: 1px;
}

QRadioButton, QCheckBox {
    spacing: 6px;
    color: #333333;
}

QScrollBar:vertical {
    background: #F5F5F5;
    width: 10px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #CCCCCC;
    border-radius: 5px;
    min-height: 20px;
}
QScrollBar::add-line, QScrollBar::sub-line {
    height: 0;
}
""".strip()


def apply_theme(app: QApplication) -> None:
    """Apply the light theme stylesheet to *app*."""
    app.setStyleSheet(_LIGHT_QSS)


# Path exposed for tests / future dynamic theme switching.
THEME_DIR = Path(__file__).parent
LIGHT_QSS_PATH = THEME_DIR / "light.qss"
