"""``narrate`` primitive — render a template string from a dict (output primitive).

Unlike the other primitives, ``narrate`` is an **output primitive**: it reduces
data to ``str`` rather than ``SheetData``. It uses ``str.format``-style templates
and supports format specs (``{x:.2f}``, ``{x:,}``). Missing keys keep their
placeholder so gaps are visible instead of raising.
"""

from __future__ import annotations

import string

from ..backends.models import SheetData

__all__ = ["narrate"]


class _KeepMissingFormatter(string.Formatter):
    """Formatter that keeps ``{key}`` literal when ``key`` is absent.

    Format specs (e.g. ``:.2f``) are still applied for present keys.
    """

    def get_value(self, key, args, kwargs):  # type: ignore[override]
        if isinstance(key, str):
            if key not in kwargs:
                return "{" + key + "}"
            return kwargs[key]
        return super().get_value(key, args, kwargs)


_FMT = _KeepMissingFormatter()


def narrate(context: dict | SheetData, template: str) -> str | list[str]:
    """Render ``template`` with values from ``context``.

    Args:
        context: A ``dict`` (single render) or a ``SheetData`` (batch render —
            one string per row).
        template: ``str.format``-style template. ``{key}`` is replaced by the
            matching value; missing ``{key}`` stays literal.

    Returns:
        A single ``str`` when ``context`` is a dict, or a ``list[str]`` (one per
        row) when ``context`` is a ``SheetData``.
    """
    if isinstance(context, SheetData):
        return [
            _FMT.format(template, **dict(zip(context.columns, row, strict=True)))
            for row in context.rows
        ]
    return _FMT.format(template, **context)
