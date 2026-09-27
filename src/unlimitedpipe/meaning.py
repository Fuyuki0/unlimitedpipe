"""Find catalog items by meaning when none has a question's words ("delisted stocks" for
"delisting notice"), with a small local embedding model through Ollama.

`unlimited setup` installs all-minilm (46 MB). Each item's vector is computed once and kept in
the cache folder, so a question costs one small embedding after the first.
"""

from __future__ import annotations

import array
import base64
import json
import math
import re
from pathlib import Path
from typing import Any

import httpx

from unlimitedpipe.context import Context

MODELS = ("all-minilm", "nomic-embed-text", "mxbai-embed-large", "snowflake-arctic-embed")
EMBED_MODEL = "all-minilm"  # what `unlimited setup` installs
# How alike a question and an item must be to count as a match (cosine similarity).
THRESHOLD = {"all-minilm": 0.40}
DEFAULT_THRESHOLD = 0.55
BATCH = 64


def is_embedding(model: str) -> bool:
    """An embedding model: it cannot answer questions."""
    return any(model.startswith(name) for name in MODELS) or "embed" in model


def pick(models: list[str]) -> str | None:
    """The embedding model to use among the installed ones, in order of MODELS."""
    return next((m for name in MODELS for m in models if m.startswith(name)), None)


def text_of(item: dict[str, Any]) -> str:
    return f"{item.get('title') or ''}. {(item.get('summary') or '')[:200]}".strip()


def _encode(vector: list[float]) -> str:
    return base64.b64encode(array.array("f", vector).tobytes()).decode()


def _decode(text: str) -> list[float]:
    values = array.array("f")
    values.frombytes(base64.b64decode(text))
    return list(values)


def _unit(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


async def _embed(client: httpx.AsyncClient, host: str, model: str, texts: list[str]):
    vectors: list[list[float]] = []
    for start in range(0, len(texts), BATCH):
        response = await client.post(
            f"{host}/api/embed", json={"model": model, "input": texts[start : start + BATCH]}
        )
        response.raise_for_status()
        vectors += [_unit(v) for v in response.json()["embeddings"]]
    return vectors


async def nearest(
    ctx: Context,
    client: httpx.AsyncClient,
    host: str,
    model: str,
    question: str,
    items: list[dict[str, Any]],
    limit: int,
) -> list[tuple[float, dict[str, Any]]]:
    """The items most alike the question, most alike first, above the model's threshold."""
    from unlimitedpipe.archive import item_key

    safe = re.sub(r"[^\w.-]+", "-", model)
    path = Path(ctx.cache_dir) / "meaning" / f"{safe}.json"
    try:
        cache: dict[str, str] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    keys = [item_key(item) for item in items]
    missing = [(k, item) for k, item in zip(keys, items, strict=True) if k not in cache]
    if missing:
        vectors = await _embed(client, host, model, [text_of(item) for _, item in missing])
        for (key, _), vector in zip(missing, vectors, strict=True):
            cache[key] = _encode(vector)
        path.parent.mkdir(parents=True, exist_ok=True)
        wanted = set(keys)  # the catalog's items now: older ones are dropped
        path.write_text(json.dumps({k: v for k, v in cache.items() if k in wanted}))
    [query] = await _embed(client, host, model, [question])
    threshold = next(
        (t for name, t in THRESHOLD.items() if model.startswith(name)), DEFAULT_THRESHOLD
    )
    scored = []
    for key, item in zip(keys, items, strict=True):
        vector = _decode(cache[key])
        score = sum(a * b for a, b in zip(query, vector, strict=False))
        if score >= threshold:
            scored.append((score, item))
    scored.sort(key=lambda pair: (pair[0], str(pair[1].get("date") or "")), reverse=True)
    seen: set[str] = set()
    unique = []
    for score, item in scored:  # one of each headline: several feeds carry the same story
        title = " ".join(str(item.get("title") or "").casefold().split())
        if title not in seen:
            seen.add(title)
            unique.append((score, item))
    return unique[:limit]
