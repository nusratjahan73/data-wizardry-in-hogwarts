"""Shared helpers. Config, logging, HTTP and file placement live here.

Importing `src.utils` from a script that was run directly (for example
`python src/collect/01_potterdb.py`) needs the repository root on the import
path. Every script does that with the two line preamble shown in
docs/word/methods.docx, which calls `bootstrap()` below.
"""

from __future__ import annotations

import sys
from pathlib import Path


def bootstrap() -> Path:
    """Put the repository root on sys.path and return it.

    Called at the top of every runnable script so that `python src/clean/10_x.py`
    behaves the same as importing the module from the root.
    """
    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return root


__all__ = ["bootstrap"]
