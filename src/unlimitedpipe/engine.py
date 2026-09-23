"""The streaming engine: sources -> operators -> outputs, one event at a time.

Every stage is an async generator. Nothing is loaded into memory unless an operator needs the
whole stream (``sort``) or an output needs to (``json`` writes one array).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from typing import Any

from unlimitedpipe.component import Operator, Output, Source
from unlimitedpipe.context import Context
from unlimitedpipe.errors import ConfigError
from unlimitedpipe.event import Event

_DONE = object()


async def _aclose(stream: Any) -> None:
    close = getattr(stream, "aclose", None)
    if close is not None:
        await close()


async def _stamp(
    events: AsyncIterator[Event],
    step: dict[str, Any] | None,
    upstream: AsyncIterator[Event] | None = None,
) -> AsyncIterator[Event]:
    """Append this stage's provenance step to every event passing through.

    Closing a stamped stage also closes the stage feeding it, so stopping early (``limit``,
    Ctrl+C, a closed pipe) stops the sources promptly.
    """
    try:
        async for event in events:
            if step is not None:
                event.provenance.append(step)
            yield event
    finally:
        await _aclose(events)
        if upstream is not None:
            await _aclose(upstream)


async def merge(streams: Sequence[AsyncIterator[Event]]) -> AsyncIterator[Event]:
    """Interleave several event streams as events arrive."""
    if len(streams) == 1:
        try:
            async for event in streams[0]:
                yield event
        finally:
            await _aclose(streams[0])
        return

    queue: asyncio.Queue[tuple[Any, Event | None]] = asyncio.Queue(maxsize=256)

    async def pump(stream: AsyncIterator[Event]) -> None:
        try:
            async for event in stream:
                await queue.put((None, event))
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            await queue.put((exc, None))
            return
        await queue.put((_DONE, None))

    tasks = [asyncio.create_task(pump(stream)) for stream in streams]
    remaining = len(tasks)
    try:
        while remaining:
            marker, event = await queue.get()
            if marker is _DONE:
                remaining -= 1
            elif marker is not None:
                raise marker
            else:
                assert event is not None
                yield event
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for stream in streams:
            await _aclose(stream)


def build_stream(
    sources: Sequence[Source], operators: Sequence[Operator], ctx: Context
) -> AsyncIterator[Event]:
    if not sources:
        raise ConfigError("a pipeline needs at least one source")
    infinite = [s.name for s in sources if not s.finite]
    for op in operators:
        if op.buffering and infinite:
            raise ConfigError(
                f"{op.name!r} needs the whole stream, but {infinite[0]!r} never ends",
                hint="put a `limit` before it",
            )
        if op.bounded:
            infinite = []
    stream = merge([_stamp(s.collect(ctx), s.provenance_step()) for s in sources])
    for op in operators:
        stream = _stamp(op.apply(stream, ctx), op.provenance_step(), upstream=stream)
    return stream


async def run_pipeline(
    sources: Sequence[Source],
    operators: Sequence[Operator],
    outputs: Sequence[Output],
    ctx: Context,
) -> int:
    """Run a pipeline to completion. Returns the number of events that reached the outputs.

    Outputs are always closed, also on errors and Ctrl+C, so files are complete and state is
    saved.
    """
    stream = build_stream(sources, operators, ctx)
    opened: list[Output] = []
    count = 0
    try:
        for output in outputs:
            await output.open(ctx)
            opened.append(output)
        async for event in stream:
            count += 1
            for output in outputs:
                await output.write(event)
    finally:
        try:
            await _aclose(stream)
        finally:
            for output in opened:
                await output.close()
            await ctx.aclose()
    return count
