"""excelops_gui — a PySide6 desktop client for the excelOps library.

Three-zone ``QMainWindow``: file/sheet navigation (left) | paginated data view
(center) | pluggable operation panels (right). The GUI layer contains **zero**
business logic: it only calls the public ``excelops`` library API.

This package is an optional extra. Importing ``excelops`` does not pull in
PySide6.
"""
