"""Polite HTTP for sources: robots.txt, per-host rate limits, retries, conditional requests.

Defaults are chosen so that watching a page every few minutes is invisible to the site:
one request per second per host, ``ETag``/``If-Modified-Since`` revalidation (a 304 costs
almost nothing), and robots.txt respected as described in RFC 9309.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import random
import re
import time
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from unlimitedpipe._version import USER_AGENT
from unlimitedpipe.errors import FetchError, RobotsDisallowed

RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
DEFAULT_INTERVAL = 1.0
MAX_CRAWL_DELAY = 30.0
ROBOTS_MAX_BYTES = 512 * 1024


def normalize_url(url: str) -> str:
    """Add ``https://`` when the scheme is missing: ``example.com`` works on the CLI."""
    url = url.strip()
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
        url = "https://" + url
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise FetchError(f"not a web URL: {url!r}", url=url, hint="use an http:// or https:// URL")
    return url


@dataclass
class Response:
    url: str
    final_url: str
    status: int
    headers: dict[str, str]
    content: bytes
    encoding: str | None
    elapsed_ms: int
    from_cache: bool = False

    @property
    def text(self) -> str:
        return self.content.decode(self.encoding or "utf-8", errors="replace")

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "").split(";")[0].strip().lower()

    def json(self) -> Any:
        try:
            return json.loads(self.content)
        except ValueError as exc:
            raise FetchError(
                f"{self.final_url} did not return JSON ({self.content_type or 'unknown type'})",
                url=self.url,
            ) from exc


@dataclass
class _Group:
    agents: list[str] = field(default_factory=list)
    rules: list[tuple[bool, str]] = field(default_factory=list)
    crawl_delay: float | None = None


class RobotsRules:
    """robots.txt rules per RFC 9309: longest matching rule wins, ``*`` and ``$`` supported."""

    def __init__(
        self,
        groups: list[_Group] | None = None,
        sitemaps: list[str] | None = None,
        deny_reason: str | None = None,
    ) -> None:
        self.groups = groups or []
        self.sitemaps = sitemaps or []
        self.deny_reason = deny_reason

    @classmethod
    def parse(cls, text: str) -> RobotsRules:
        groups: list[_Group] = []
        sitemaps: list[str] = []
        current: _Group | None = None
        in_agents = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            key, sep, value = line.partition(":")
            if not sep:
                continue
            key, value = key.strip().lower(), value.strip()
            if key == "user-agent":
                if current is None or not in_agents:
                    current = _Group()
                    groups.append(current)
                current.agents.append(value.split("/")[0].strip().lower())
                in_agents = True
            elif key in ("allow", "disallow") and current is not None:
                in_agents = False
                if value:
                    current.rules.append((key == "allow", value))
            elif key == "crawl-delay" and current is not None:
                in_agents = False
                with contextlib.suppress(ValueError):
                    current.crawl_delay = float(value)
            elif key == "sitemap":
                sitemaps.append(value)
        return cls(groups, sitemaps)

    def _groups_for(self, agent: str) -> list[_Group]:
        agent = agent.lower()
        exact = [g for g in self.groups if agent in g.agents]
        return exact or [g for g in self.groups if "*" in g.agents]

    def allowed(self, agent: str, path: str) -> bool:
        if self.deny_reason is not None:
            return False
        best: tuple[int, bool] | None = None
        for group in self._groups_for(agent):
            for allow, pattern in group.rules:
                if _robots_match(pattern, path):
                    candidate = (len(pattern), allow)
                    if best is None or candidate > best:
                        best = candidate
        return True if best is None else best[1]

    def crawl_delay(self, agent: str) -> float | None:
        delays = [g.crawl_delay for g in self._groups_for(agent) if g.crawl_delay is not None]
        return max(delays) if delays else None


def _robots_match(pattern: str, path: str) -> bool:
    anchored = pattern.endswith("$")
    body = re.escape(pattern[:-1] if anchored else pattern).replace(r"\*", ".*")
    return re.match(body + ("$" if anchored else ""), path) is not None


def _describe(exc: Exception, url: str) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return f"{url} timed out"
    if isinstance(exc, httpx.ConnectError):
        detail = re.sub(r"^\[Errno [^\]]+\]\s*", "", str(exc)) or "connection failed"
        return f"could not connect to {urlsplit(url).netloc} ({detail})"
    return f"{url}: {exc or type(exc).__name__}"


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        return max(0.0, parsedate_to_datetime(value).timestamp() - time.time())
    except (TypeError, ValueError):
        return None


async def _refuse_private_hosts(request: httpx.Request) -> None:
    """Runs before every request, redirects included: refuse hosts on private networks, so
    content an agent reads cannot steer it to internal services or cloud metadata."""
    import ipaddress

    host = request.url.host
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, None)
    except OSError:
        return  # unresolvable: the request itself fails with a clear message
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if not address.is_global:
            raise FetchError(
                f"{host} resolves to a private address ({address}); only the public web is allowed",
                url=str(request.url),
                hint="start `unlimited mcp` with --allow-private to lift this in trusted setups",
            )


class HttpClient:
    """One client per pipeline run, shared by all sources."""

    def __init__(
        self,
        *,
        cache_dir: Path,
        transport: httpx.AsyncBaseTransport | None = None,
        interval: float = DEFAULT_INTERVAL,
        public_only: bool = False,
    ) -> None:
        self.cache_dir = cache_dir
        self.interval = interval
        hooks = {"request": [_refuse_private_hosts]} if public_only else {}
        self._client = httpx.AsyncClient(
            follow_redirects=True,
            max_redirects=10,
            transport=transport,
            headers={"User-Agent": USER_AGENT},
            event_hooks=hooks,
        )
        self._next_slot: dict[str, float] = {}
        self._host_locks: dict[str, asyncio.Lock] = {}
        self._robots: dict[str, RobotsRules] = {}
        self._robots_locks: dict[str, asyncio.Lock] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _throttle(self, host: str, interval: float) -> None:
        lock = self._host_locks.setdefault(host, asyncio.Lock())
        async with lock:
            now = time.monotonic()
            wait = self._next_slot.get(host, 0.0) - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._next_slot[host] = max(now, self._next_slot.get(host, 0.0)) + interval

    async def robots(self, url: str, *, user_agent: str | None = None) -> RobotsRules:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin in self._robots:
            return self._robots[origin]
        async with self._robots_locks.setdefault(origin, asyncio.Lock()):
            if origin in self._robots:
                return self._robots[origin]
            robots_url = origin + "/robots.txt"
            try:
                response = await self.get(
                    robots_url,
                    timeout=10.0,
                    retries=1,
                    raise_for_status=False,
                    cache=False,
                    user_agent=user_agent,
                    max_bytes=ROBOTS_MAX_BYTES,
                )
            except FetchError:
                # The host itself is unreachable: report that, not a robots.txt problem.
                raise
            else:
                if response.status < 400:
                    rules = RobotsRules.parse(response.text)
                elif response.status < 500:
                    rules = RobotsRules()
                else:
                    rules = RobotsRules(deny_reason=f"{robots_url} returned HTTP {response.status}")
            self._robots[origin] = rules
            return rules

    def _cache_files(self, url: str) -> tuple[Path, Path]:
        digest = hashlib.sha256(url.encode()).hexdigest()[:32]
        return self.cache_dir / f"{digest}.json", self.cache_dir / f"{digest}.body"

    def _load_cached(self, url: str) -> dict[str, Any] | None:
        meta_path, body_path = self._cache_files(url)
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta["content"] = body_path.read_bytes()
            return meta if meta.get("url") == url else None
        except (OSError, ValueError):
            return None

    def _store_cached(self, response: Response) -> None:
        validators = {k: response.headers.get(k) for k in ("etag", "last-modified")}
        if not any(validators.values()):
            return
        meta_path, body_path = self._cache_files(response.url)
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            body_path.write_bytes(response.content)
            meta = {
                "url": response.url,
                "final_url": response.final_url,
                "status": response.status,
                "headers": response.headers,
                "encoding": response.encoding,
                **validators,
            }
            meta_path.write_text(json.dumps(meta), encoding="utf-8")
        except OSError:
            pass  # the cache is an optimization; never fail a fetch because of it

    async def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 20.0,
        user_agent: str | None = None,
        robots: bool = False,
        cache: bool = True,
        interval: float | None = None,
        retries: int = 2,
        raise_for_status: bool = True,
        max_bytes: int = 20_000_000,
    ) -> Response:
        """GET a URL politely. Raises FetchError with a readable message on failure."""
        if params:
            url = str(httpx.URL(url, params=params))
        request_headers = dict(headers or {})
        if user_agent:
            request_headers["User-Agent"] = user_agent
        interval = self.interval if interval is None else interval
        agent_token = (user_agent or USER_AGENT).split("/")[0].split()[0].lower()
        host = urlsplit(url).netloc.lower()

        if robots:
            rules = await self.robots(url, user_agent=user_agent)
            parts = urlsplit(url)
            path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
            if not rules.allowed(agent_token, path):
                reason = rules.deny_reason or "robots.txt does not allow this path"
                raise RobotsDisallowed(
                    f"not fetching {url}: {reason}",
                    url=url,
                    hint="UnlimitedPipe respects robots.txt by default. Use --ignore-robots only "
                    "if the site owner allows it.",
                )
            delay = rules.crawl_delay(agent_token)
            if delay:
                interval = max(interval, min(delay, MAX_CRAWL_DELAY))

        cached = self._load_cached(url) if cache else None
        if cached:
            if cached.get("etag"):
                request_headers["If-None-Match"] = cached["etag"]
            if cached.get("last-modified"):
                request_headers["If-Modified-Since"] = cached["last-modified"]

        error = f"{url}: unknown error"
        for attempt in range(retries + 1):
            await self._throttle(host, interval)
            started = time.monotonic()
            try:
                async with self._client.stream(
                    "GET", url, headers=request_headers, timeout=timeout
                ) as raw:
                    if raw.status_code in RETRY_STATUS and attempt < retries:
                        delay = _retry_after(raw) or (2**attempt + random.random())
                        await asyncio.sleep(min(delay, 60.0))
                        continue
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in raw.aiter_bytes():
                        size += len(chunk)
                        if size > max_bytes:
                            raise FetchError(
                                f"{url} is over {max_bytes // 1_000_000} MB; not downloading",
                                url=url,
                            )
                        chunks.append(chunk)
                    elapsed = int((time.monotonic() - started) * 1000)
            except httpx.TooManyRedirects:
                raise FetchError(f"{url} redirects too many times", url=url) from None
            except (httpx.InvalidURL, httpx.UnsupportedProtocol) as exc:
                raise FetchError(f"invalid URL {url!r}: {exc}", url=url) from None
            except httpx.HTTPError as exc:
                error = _describe(exc, url)
                if attempt < retries:
                    await asyncio.sleep(2**attempt + random.random())
                    continue
                raise FetchError(
                    error,
                    url=url,
                    hint="check the URL and your connection; slow sites may need --timeout",
                ) from None

            if raw.status_code == 304 and cached:
                return Response(
                    url=url,
                    final_url=cached.get("final_url") or url,
                    status=cached.get("status", 200),
                    headers=cached.get("headers") or {},
                    content=cached["content"],
                    encoding=cached.get("encoding"),
                    elapsed_ms=elapsed,
                    from_cache=True,
                )
            response = Response(
                url=url,
                final_url=str(raw.url),
                status=raw.status_code,
                headers={k.lower(): v for k, v in raw.headers.items()},
                content=b"".join(chunks),
                encoding=raw.charset_encoding,
                elapsed_ms=elapsed,
            )
            if raise_for_status and response.status >= 400:
                raise FetchError(
                    f"{url} returned HTTP {response.status} {raw.reason_phrase}".rstrip(),
                    url=url,
                    hint=_status_hint(response.status, response.headers),
                )
            if cache and response.status == 200:
                self._store_cached(response)
            return response
        raise FetchError(error, url=url)

    async def post(
        self,
        url: str,
        *,
        json_body: Any,
        headers: dict[str, str] | None = None,
        timeout: float = 20.0,
        retries: int = 2,
        secret_url: bool = True,
    ) -> Response:
        """POST JSON with the same per-host throttling and retries as ``get``.

        With ``secret_url`` (the default: webhook URLs contain credentials), messages show only
        the host.
        """
        shown = redact_url(url) if secret_url else url
        host = urlsplit(url).netloc.lower()
        error = f"{shown}: unknown error"
        for attempt in range(retries + 1):
            await self._throttle(host, self.interval)
            started = time.monotonic()
            try:
                raw = await self._client.post(url, json=json_body, headers=headers, timeout=timeout)
            except (httpx.InvalidURL, httpx.UnsupportedProtocol):
                raise FetchError(f"invalid URL {shown}", url=shown) from None
            except httpx.HTTPError as exc:
                error = _describe(exc, shown)
                if attempt < retries:
                    await asyncio.sleep(2**attempt + random.random())
                    continue
                raise FetchError(
                    error, url=shown, hint="check the URL and your connection"
                ) from None
            if raw.status_code in RETRY_STATUS and attempt < retries:
                delay = (
                    _retry_after(raw) or _json_retry_after(raw) or (2**attempt + random.random())
                )
                await asyncio.sleep(min(delay, 60.0))
                continue
            response = Response(
                url=shown,
                final_url=shown,
                status=raw.status_code,
                headers={k.lower(): v for k, v in raw.headers.items()},
                content=raw.content,
                encoding=raw.charset_encoding,
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )
            if response.status >= 400:
                detail = response.text.strip()[:200]
                raise FetchError(
                    f"{shown} returned HTTP {response.status}" + (f": {detail}" if detail else ""),
                    url=shown,
                    hint="check that the webhook URL is complete and still active"
                    if response.status in (401, 403, 404)
                    else None,
                )
            return response
        raise FetchError(error, url=shown)


def redact_url(url: str) -> str:
    """``https://discord.com/api/webhooks/123/SECRET`` -> ``https://discord.com/…``: webhook URLs
    carry their credentials, so they never appear in messages or logs."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}/…" if parts.netloc else "(webhook URL)"


def _json_retry_after(response: httpx.Response) -> float | None:
    """Discord and others put the wait in the JSON body: ``{"retry_after": 1.5}``."""
    try:
        value = response.json().get("retry_after")
        return max(0.0, float(value)) if value is not None else None
    except (ValueError, AttributeError, TypeError):
        return None


def _status_hint(status: int, headers: dict[str, str] | None = None) -> str | None:
    headers = headers or {}
    if status in (403, 429) and headers.get("x-ratelimit-remaining") == "0":
        return "the API's rate limit is used up for now; try again later or use an API token"
    if status == 404:
        return "check the URL"
    if status in (401, 403):
        return (
            "the site refuses automated or anonymous access; UnlimitedPipe does not try to get "
            "around blocks. Look for an official API or feed: unlimited inspect URL"
        )
    if status == 429:
        return "the site is rate limiting; try again later or less often"
    return None
