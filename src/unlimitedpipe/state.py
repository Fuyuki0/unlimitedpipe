"""Small JSON state files kept between runs (diff, trend)."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from unlimitedpipe.context import Context


def state_path(ctx: Context, kind: str, namespace: str, explicit: str | None = None) -> Path:
    """``<state dir>/<kind>/<namespace>.json``, or an explicit file."""
    if explicit:
        return Path(explicit).expanduser()
    safe = re.sub(r"[^\w.-]+", "-", namespace).strip("-") or "default"
    return ctx.state_dir / kind / f"{safe}.json"


def write_json_atomic(path: Path, payload: Any) -> None:
    """Write through a temporary file, so an interrupted run never leaves half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")
    os.replace(tmp, path)
