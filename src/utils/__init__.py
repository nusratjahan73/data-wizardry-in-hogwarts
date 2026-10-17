"""Sharing my helper code for config, logging, HTTP and saving files in the right folder.

When I run a script directly (for example `python src/collect/01_potterdb.py`),
Python needs my project folder on the import path before it can import `src.utils`.
Every script does that with the two line start shown in docs/word/methods.docx,
which calls `bootstrap()` below.
"""

from __future__ import annotations

import sys
from pathlib import Path


def bootstrap() -> Path:
    """Adding my project folder to sys.path and returning it.

    I call this at the top of every script, so running `python src/clean/10_x.py`
    directly works the same as importing the module from the project folder.
    """
    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return root


__all__ = ["bootstrap"]
