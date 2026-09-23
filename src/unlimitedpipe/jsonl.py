"""Reading events from a byte stream (stdin) without blocking the event loop."""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import queue
import threading
from collections.abc import AsyncIterator
from typing import BinaryIO

from unlimitedpipe.errors import InputError
from unlimitedpipe.event import Event

_EOF = object()


async def read_lines(stream: BinaryIO, *, chunk_size: int = 65536) -> AsyncIterator[bytes]:
    """Yield lines from a blocking binary stream, read on a background thread.

    Lines are handed over as soon as they arrive, so slow real-time producers stream through
    immediately while fast producers are batched. The thread only touches a thread-safe queue
    and wakes the loop with ``call_soon_threadsafe``, so it can outlive the event loop (after
    ``limit`` or Ctrl+C) without errors.
    """
    loop = asyncio.get_running_loop()
    handoff: queue.Queue[object] = queue.Queue(maxsize=64)
    ready = asyncio.Event()

    try:
        # Read the file descriptor directly: a thread blocked in os.read holds no Python-level
        # lock, so the process can exit cleanly while it waits.
        fd = stream.fileno()

        def read(size: int) -> bytes:
            return os.read(fd, size)

    except (AttributeError, OSError, io.UnsupportedOperation):
        read_chunk = getattr(stream, "read1", stream.read)

        def read(size: int) -> bytes:
            return read_chunk(size)

    def hand_over(item: object) -> None:
        handoff.put(item)  # blocks while the consumer is behind: backpressure
        with contextlib.suppress(RuntimeError):  # the loop is closed: nobody is listening
            loop.call_soon_threadsafe(ready.set)

    def pump() -> None:
        pending = b""
        try:
            while True:
                chunk = read(chunk_size)
                if not chunk:
                    break
                pending += chunk
                *lines, pending = pending.split(b"\n")
                if lines:
                    hand_over(lines)
            if pending.strip():
                hand_over([pending])
        except Exception as exc:
            hand_over(exc)
        hand_over(_EOF)

    threading.Thread(target=pump, name="unlimitedpipe-stdin", daemon=True).start()
    while True:
        try:
            item = handoff.get_nowait()
        except queue.Empty:
            ready.clear()
            try:  # check again after clearing, so a wake-up between the two is not lost
                item = handoff.get_nowait()
            except queue.Empty:
                await ready.wait()
                continue
        if item is _EOF:
            return
        if isinstance(item, Exception):
            raise item
        assert isinstance(item, list)
        for line in item:
            yield line


async def read_events(
    stream: BinaryIO, *, name: str = "stdin", lenient: bool = False
) -> AsyncIterator[Event]:
    """Parse JSONL events. Plain JSON objects are wrapped as ``record`` events.

    With ``lenient``, lines that are not JSON become ``{"value": line}`` records: sources use
    this to accept plain lists of URLs.
    """
    lineno = 0
    async for line in read_lines(stream):
        lineno += 1
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            if lenient:
                text = line.decode("utf-8", errors="replace").strip()
                yield Event(source=name, type="record", data={"value": text})
                continue
            preview = line[:60].decode(errors="replace")
            raise InputError(
                f"{name} line {lineno} is not valid JSON ({exc.msg}): {preview!r}",
                hint="UnlimitedPipe stages exchange JSONL events, one JSON object per line",
            ) from None
        yield Event.from_dict(value)
