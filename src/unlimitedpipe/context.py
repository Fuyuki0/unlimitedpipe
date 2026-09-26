"""Runtime context shared by the components of one pipeline run."""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click

from unlimitedpipe.errors import UnlimitedError
from unlimitedpipe.event import Event

if TYPE_CHECKING:
    from unlimitedpipe.browser import Browser
    from unlimitedpipe.http import HttpClient

log = logging.getLogger("unlimitedpipe")


def _dir_from_env(env: str, kind: str) -> Path:
    override = os.environ.get(env)
    if override:
        return Path(override).expanduser()
    import platformdirs

    if kind == "state":
        return Path(platformdirs.user_state_dir("unlimitedpipe"))
    return Path(platformdirs.user_cache_dir("unlimitedpipe"))


class Context:
    """What a component can use while it runs: HTTP, state and cache dirs, error reporting.

    ``input`` carries events piped into a source command (for example URLs for ``web``), or
    None when nothing is piped in.
    """

    def __init__(
        self,
        *,
        errors_as_events: bool = False,
        quiet: bool = False,
        input: AsyncIterator[Event] | None = None,
        transport: Any = None,
        state_dir: Path | None = None,
        cache_dir: Path | None = None,
        host_interval: float | None = None,
        public_only: bool = False,
        browser: Any = None,
    ) -> None:
        self.errors_as_events = errors_as_events
        self.quiet = quiet
        self.input = input
        self.failures = 0
        self._transport = transport
        self._state_dir = state_dir
        self._cache_dir = cache_dir
        self._http: HttpClient | None = None
        self._browser = browser
        self._host_interval = host_interval
        self.public_only = public_only

    @property
    def state_dir(self) -> Path:
        if self._state_dir is None:
            self._state_dir = _dir_from_env("UNLIMITEDPIPE_STATE_DIR", "state")
        return self._state_dir

    @property
    def cache_dir(self) -> Path:
        if self._cache_dir is None:
            self._cache_dir = _dir_from_env("UNLIMITEDPIPE_CACHE_DIR", "cache")
        return self._cache_dir

    @property
    def transport(self) -> Any:
        """The HTTP transport for clients that talk to model APIs rather than the public web
        (None outside tests)."""
        return self._transport

    @property
    def http(self) -> HttpClient:
        """Shared HTTP client: per-host rate limits, retries, robots.txt, conditional requests."""
        if self._http is None:
            from unlimitedpipe.http import DEFAULT_INTERVAL, HttpClient

            interval = DEFAULT_INTERVAL if self._host_interval is None else self._host_interval
            self._http = HttpClient(
                cache_dir=self.cache_dir / "http",
                transport=self._transport,
                interval=interval,
                public_only=self.public_only,
            )
        return self._http

    @property
    def browser(self) -> Browser:
        """A headless browser for pages that need JavaScript, started on first use."""
        if self._browser is None:
            from unlimitedpipe.browser import Browser

            self._browser = Browser(self.http)
        return self._browser

    def notice(self, message: str) -> None:
        """A short human message on stderr. Never mixed into the event stream."""
        if not self.quiet:
            click.echo(click.style(message, dim=True), err=True)

    def warn(self, message: str) -> None:
        if not self.quiet:
            click.echo(click.style("warning: ", fg="yellow", bold=True) + message, err=True)

    def fail(self, exc: Exception, *, source: str, url: str | None = None) -> Event | None:
        """Report a per-item failure without stopping the pipeline.

        Returns an ``error`` event to emit when ``--errors-as-events`` is on, else prints the
        error and returns None. Either way the run finishes with the remaining items.
        """
        message = exc.message if isinstance(exc, UnlimitedError) else f"{type(exc).__name__}: {exc}"
        hint = exc.hint if isinstance(exc, UnlimitedError) else None
        log.debug("failure in %s for %s", source, url, exc_info=exc)
        if self.errors_as_events:
            return Event(
                source=source,
                type="error",
                source_url=url,
                key=url,
                data={"error": message, "hint": hint, "url": url},
            )
        self.failures += 1
        click.echo(click.style("error: ", fg="red", bold=True) + message, err=True)
        if hint:
            click.echo(click.style("hint: ", fg="cyan") + hint, err=True)
        return None

    async def aclose(self) -> None:
        if self._browser is not None:
            await self._browser.aclose()
            self._browser = None
        if self._http is not None:
            await self._http.aclose()
            self._http = None
