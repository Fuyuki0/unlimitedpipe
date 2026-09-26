"""Rendering pages that need JavaScript, with a headless browser (optional).

Some public pages only fill in their content with JavaScript. `web --browser` opens them in a
headless Chromium (Playwright) and reads the finished page, under the same rules as every other
fetch: robots.txt, one request per host at a time with the same pacing, an honest User-Agent.
Images, fonts and media are not downloaded unless a screenshot is taken.

Install: pip install "unlimitedpipe[browser]" && playwright install chromium
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

from unlimitedpipe._version import USER_AGENT
from unlimitedpipe.errors import FetchError, UsageError
from unlimitedpipe.http import HttpClient, Response

SKIPPED = frozenset({"image", "media", "font"})


class Browser:
    """One headless browser per run, opened on first use and closed with the run."""

    def __init__(self, http: HttpClient) -> None:
        self._http = http
        self._playwright: Any = None
        self._browser: Any = None

    async def _open(self) -> Any:
        if self._browser is None:
            try:
                from playwright.async_api import async_playwright
            except ImportError:
                raise UsageError(
                    "rendering pages needs the browser extra",
                    hint='pip install "unlimitedpipe[browser]" && playwright install chromium',
                ) from None
            self._playwright = await async_playwright().start()
            try:
                self._browser = await self._playwright.chromium.launch(headless=True)
            except Exception as exc:  # Playwright raises its own error types
                await self._playwright.stop()
                self._playwright = None
                raise UsageError(
                    f"could not start the headless browser: {str(exc).splitlines()[0]}",
                    hint="playwright install chromium   (add --with-deps on a fresh Linux)",
                ) from None
        return self._browser

    async def render(
        self,
        url: str,
        *,
        user_agent: str | None = None,
        robots: bool = True,
        timeout: float = 30.0,
        screenshot: Path | None = None,
    ) -> tuple[Response, Path | None]:
        """The page as the browser shows it after its scripts ran, and the screenshot file."""
        interval = await self._http.check_robots(url, user_agent=user_agent) if robots else None
        await self._http.pace(url, interval)
        browser = await self._open()
        context = await browser.new_context(user_agent=user_agent or USER_AGENT)
        try:
            page = await context.new_page()
            if screenshot is None:

                async def skip_heavy(route: Any) -> None:
                    if route.request.resource_type in SKIPPED:
                        await route.abort()
                    else:
                        await route.continue_()

                await page.route("**/*", skip_heavy)
            started = time.monotonic()
            try:
                answer = await page.goto(url, wait_until="networkidle", timeout=timeout * 1000)
            except Exception as exc:
                raise FetchError(
                    f"{url} did not finish loading in the browser: {str(exc).splitlines()[0]}",
                    url=url,
                    hint="slow pages may need --timeout",
                ) from None
            status = answer.status if answer is not None else 200
            if status >= 400:
                raise FetchError(f"{url} returned HTTP {status}", url=url)
            content = (await page.content()).encode("utf-8")
            elapsed = int((time.monotonic() - started) * 1000)
            shot = None
            if screenshot is not None:
                screenshot.mkdir(parents=True, exist_ok=True)
                stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
                name = hashlib.sha256(url.encode()).hexdigest()[:12]
                shot = screenshot / f"{name}-{stamp}.png"
                await page.screenshot(path=str(shot), full_page=True)
            response = Response(
                url=url,
                final_url=page.url,
                status=status,
                headers={"content-type": "text/html; charset=utf-8"},
                content=content,
                encoding="utf-8",
                elapsed_ms=elapsed,
            )
            return response, shot
        finally:
            await context.close()

    async def aclose(self) -> None:
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
