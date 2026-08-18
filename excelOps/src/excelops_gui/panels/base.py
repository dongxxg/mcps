"""Abstract base for operation panels and the decorator-based registry.

Design decision D3: a decorator registry keeps the "add a new operation" path to
a single-line change (import the module so its ``@register_panel("name")`` fires).
The base classes stay dependency-light — only PySide6 ``QtCore/QtWidgets`` plus
the ``excelops`` library for type hints.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field

from PySide6.QtWidgets import QWidget  # type: ignore[import-untyped]

from excelops.backends.models import SheetData

_PANEL_REGISTRY: dict[str, type[BasePanel]] = {}


# ─── result dataclasses ────────────────────────────────────────────────────

@dataclass(frozen=True)
class PanelContext:
    """Immutable context handed to :meth:`BasePanel.execute`."""

    file_path: str | None = None
    sheet_name: str | None = None
    sheet_data: SheetData | None = None
    directory: str | None = None
    extra: dict[str, object] = field(default_factory=dict, hash=False)


@dataclass(frozen=True)
class PanelResult:
    """Outcome of a panel execution."""

    sheet_data: SheetData | None = None
    message: str = ""
    error: str | None = None


# ─── registry helpers ──────────────────────────────────────────────────────

def register_panel(name: str, title: str):
    """Decorator that registers a :class:`BasePanel` subclass in the global registry."""

    def decorator(cls: type[BasePanel]) -> type[BasePanel]:
        _PANEL_REGISTRY[name] = cls
        cls.PANEL_NAME = name
        cls.PANEL_TITLE = title
        return cls

    return decorator


def get_panel(name: str) -> type[BasePanel]:
    """Return the registered panel class for *name*."""
    if name not in _PANEL_REGISTRY:
        raise KeyError(f"no panel registered as {name!r}")
    return _PANEL_REGISTRY[name]


def registered_panels() -> dict[str, str]:
    """Return ``{name: title}`` for every registered panel."""
    return {name: cls.PANEL_TITLE for name, cls in _PANEL_REGISTRY.items()}


def _iter_registered() -> Iterable[tuple[str, type[BasePanel]]]:
    return list(_PANEL_REGISTRY.items())


# ─── base panel ────────────────────────────────────────────────────────────

class BasePanel(ABC):
    """Abstract base for operation panels.

    Subclasses override :meth:`build_ui` (returns the panel's widget) and
    :meth:`execute` (returns a :class:`PanelResult`). The registry attaches
    ``PANEL_NAME`` and ``PANEL_TITLE`` class attributes.
    """

    PANEL_NAME = ""
    PANEL_TITLE = ""

    @abstractmethod
    def build_ui(self) -> QWidget:
        """Build and return the panel's top-level widget."""
        ...

    @abstractmethod
    def execute(self, ctx: PanelContext) -> PanelResult:
        """Run the operation and return the result."""
        ...
