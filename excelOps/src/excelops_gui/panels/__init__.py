"""Operation panels — pluggable UI + execution via decorator registry.

Each operation (search, filter, transform, …) is a ``BasePanel`` subclass
registered with ``@register_panel("name")``. Importing this package triggers
the registration side-effect for all currently available panels.
"""

from __future__ import annotations

from .base import BasePanel, PanelContext, PanelResult, get_panel, register_panel, registered_panels

__all__ = [
    "BasePanel",
    "PanelContext",
    "PanelResult",
    "get_panel",
    "register_panel",
    "registered_panels",
]

# Import concrete panels so their @register_panel decorators fire at import
# time. Add a new panel here when a new operation ships.
from . import search  # noqa: F401  - registers the search panel
