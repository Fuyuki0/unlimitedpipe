"""Built-in outputs: each consumes a stream of events."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TextIO


def open_target(path: str | None, *, append: bool = False) -> tuple[TextIO, bool]:
    """Open ``path`` for writing, or stdout for None / ``-``. Returns (stream, is_stdout)."""
    if path in (None, "-"):
        return sys.stdout, True
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    return target.open("a" if append else "w", encoding="utf-8", newline=""), False
