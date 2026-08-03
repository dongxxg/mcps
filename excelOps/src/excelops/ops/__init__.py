"""Pure-functional business operations on ``SheetData`` (no pandas, no I/O).

The ``ops`` layer sits above ``backends/`` and provides reusable, composable
transformations for real-world spreadsheet workflows. All functions here are
**pure**: they consume ``SheetData`` and return new ``SheetData``, never mutating
their inputs and never touching the filesystem.

Primitives (the foundation):
    - :func:`project` — select + reorder + rename columns
    - :func:`union` — vertical stack with column-name alignment
    - :func:`derive` — add a computed column (``fn(dict) -> value``)
    - :func:`filter` — keep rows matching ``predicate(dict) -> bool``
    - :func:`lookup` — priority key fallback + column fetch
    - :func:`narrate` — render a template string from a dict (output primitive)

Recipes (domain-specific compositions of the primitives above):
    - :func:`combine_reports` — merge multiple similar reports
    - :func:`lookup_product` — code → barcode → name fallback price lookup
    - :func:`calc_shelf_life` — configurable shelf-life fraction check
    - :func:`project_columns` — column projection alias
    - :func:`narrate_stats` — batch text rendering from a stats sheet
    - :func:`transform_tables` — multi-table transformation into a target sheet
"""

from .column_project import project_columns
from .combine import combine_reports
from .derive import derive
from .filter import filter
from .lookup import lookup
from .narrate import narrate
from .product_lookup import lookup_product
from .project import project
from .shelf_life import calc_shelf_life
from .stats_narrate import narrate_stats
from .transform import transform_tables
from .union import union

__all__ = [
    # primitives
    "project",
    "union",
    "derive",
    "filter",
    "lookup",
    "narrate",
    # recipes
    "combine_reports",
    "lookup_product",
    "calc_shelf_life",
    "project_columns",
    "narrate_stats",
    "transform_tables",
]
