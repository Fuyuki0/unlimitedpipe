"""Run a pipeline again and again on an interval, in one process.

A watch never dies of a bad run: failures are reported and the next run happens on schedule.
A pipeline file is reloaded when it changes; if the new version is invalid, the last valid one
keeps running.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

import click

from unlimitedpipe.component import Output
from unlimitedpipe.config import Pipeline
from unlimitedpipe.errors import UnlimitedError, UsageError

log = logging.getLogger("unlimitedpipe.watch")

UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
MIN_INTERVAL = 30.0


def parse_duration(text: str) -> float:
    """``30s``, ``5m``, ``1h30m``, ``1d`` -> seconds."""
    cleaned = text.strip().lower().replace(" ", "")
    parts = re.findall(r"(\d+(?:\.\d+)?)([smhd])", cleaned)
    if not parts or "".join(n + u for n, u in parts) != cleaned:
        raise UsageError(
            f"invalid duration {text!r}", hint="use a number and a unit: 30s, 5m, 1h, 1h30m, 1d"
        )
    return sum(float(number) * UNITS[unit] for number, unit in parts)


def format_duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds % 86400 == 0:
        return f"{seconds // 86400}d"
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    if seconds % 60 == 0:
        return f"{seconds // 60}m"
    return f"{seconds}s"


class Watch:
    def __init__(
        self,
        load: Callable[[], Pipeline],
        *,
        every: float,
        jitter: float = 0.1,
        times: int | None = None,
        quiet: bool = False,
        reload_path: Path | None = None,
        default_outputs: Callable[[], list[Output]] = list,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.load = load
        self.every = every
        self.jitter = jitter
        self.times = times
        self.quiet = quiet
        self.reload_path = reload_path
        self.default_outputs = default_outputs
        self.sleep = sleep
        self.runs = 0

    def say(self, message: str, *, dim: bool = True) -> None:
        if not self.quiet:
            stamp = datetime.now().strftime("%H:%M:%S")
            click.echo(click.style(f"[{stamp}] {message}", dim=dim), err=True)

    def _mtime(self) -> float | None:
        try:
            return self.reload_path.stat().st_mtime if self.reload_path else None
        except OSError:
            return None

    def run_once(self, pipeline: Pipeline) -> tuple[int, int]:
        """One run. Returns (events, failures); never raises except for Ctrl+C."""
        from unlimitedpipe.context import Context
        from unlimitedpipe.engine import run_pipeline

        ctx = Context(errors_as_events=pipeline.errors_as_events, quiet=self.quiet)
        outputs = pipeline.outputs or self.default_outputs()
        try:
            count = asyncio.run(run_pipeline(pipeline.sources, pipeline.operators, outputs, ctx))
        except UnlimitedError as exc:
            message = exc.message + (f" ({exc.hint})" if exc.hint else "")
            click.echo(click.style("error: ", fg="red", bold=True) + message, err=True)
            return 0, ctx.failures + 1
        except Exception as exc:
            log.debug("run failed", exc_info=exc)
            click.echo(
                click.style("error: ", fg="red", bold=True)
                + f"run failed: {type(exc).__name__}: {exc} (run with -vv for details)",
                err=True,
            )
            return 0, ctx.failures + 1
        return count, ctx.failures

    def run(self) -> None:
        pipeline = self.load()
        mtime = self._mtime()
        every = format_duration(self.every)
        self.say(f"watching every {every}; Ctrl+C to stop")
        while True:
            current = self._mtime()
            if current != mtime:
                mtime = current
                try:
                    pipeline = self.load()
                    self.say(f"reloaded {self.reload_path}")
                except UnlimitedError as exc:
                    self.say(f"{exc.message}; still running the previous version", dim=False)
            self.runs += 1
            started = time.monotonic()
            events, failures = self.run_once(pipeline)
            summary = f"run {self.runs}: {events} event(s)"
            if failures:
                summary += f", {failures} failure(s)"
            if self.times is not None and self.runs >= self.times:
                self.say(summary)
                return
            delay = self.every * (1 + random.uniform(0, self.jitter))
            wait = started + delay - time.monotonic()
            if wait < 0:
                self.say(f"{summary}; the run took longer than {every}, starting the next now")
                wait = 0
            else:
                next_at = (datetime.now() + timedelta(seconds=wait)).strftime("%H:%M:%S")
                self.say(f"{summary}; next run at {next_at}")
            self.sleep(wait)
