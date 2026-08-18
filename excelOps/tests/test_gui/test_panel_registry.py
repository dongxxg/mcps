"""Tests for the panel decorator registry."""

from __future__ import annotations

from excelops_gui.panels.base import BasePanel, PanelContext, PanelResult, get_panel, register_panel, registered_panels
from PySide6.QtWidgets import QWidget  # type: ignore[import-untyped]


@register_panel("demo", "演示面板")
class DemoPanel(BasePanel):
    def build_ui(self) -> QWidget:
        return QWidget()

    def execute(self, ctx: PanelContext) -> PanelResult:
        return PanelResult(message="demo")


def test_register_decorated_panel_is_findable() -> None:
    cls = get_panel("demo")
    assert cls is DemoPanel
    assert cls.PANEL_NAME == "demo"
    assert cls.PANEL_TITLE == "演示面板"


def test_registered_panels_returns_name_title_map() -> None:
    panels = registered_panels()
    assert panels["demo"] == "演示面板"
    # search panel should also be registered (imported via panels.__init__)
    assert "search" in panels


def test_get_unregistered_panel_raises_key_error() -> None:
    try:
        get_panel("nonexistent")
    except KeyError as exc:
        assert "nonexistent" in str(exc)
    else:
        raise AssertionError("expected KeyError")
