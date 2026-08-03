"""``narrate_stats`` recipe — batch text rendering from a stats sheet."""

from __future__ import annotations

from ..backends.models import SheetData
from .narrate import narrate

__all__ = ["narrate_stats"]


def narrate_stats(sd: SheetData, template: str) -> list[str]:
    """Render one description string per row of ``sd`` using ``template``.

    Convenience wrapper around :func:`narrate` for the common case of rendering
    a description for every row of a stats sheet.
    """
    return narrate(sd, template)
