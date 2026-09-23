import asyncio

import httpx
import pytest

from unlimitedpipe.errors import FetchError, RobotsDisallowed
from unlimitedpipe.http import HttpClient, RobotsRules, normalize_url

ROBOTS = """
User-agent: *
Disallow: /private
Allow: /private/public
Disallow: /*.pdf$
Crawl-delay: 2

User-agent: UnlimitedPipe
User-agent: OtherBot
Disallow: /no-pipes

Sitemap: https://site.example/sitemap.xml
"""


def test_robots_longest_match_wildcards_and_groups():
    rules = RobotsRules.parse(ROBOTS)
    assert rules.allowed("somebot", "/")
    assert not rules.allowed("somebot", "/private/x")
    assert rules.allowed("somebot", "/private/public/x")
    assert not rules.allowed("somebot", "/files/a.pdf")
    assert rules.allowed("somebot", "/files/a.pdf?x=1")
    # UnlimitedPipe has its own group, so the * group does not apply to it.
    assert rules.allowed("unlimitedpipe", "/private/x")
    assert not rules.allowed("unlimitedpipe", "/no-pipes/y")
    assert rules.crawl_delay("somebot") == 2
    assert rules.crawl_delay("unlimitedpipe") is None
    assert rules.sitemaps == ["https://site.example/sitemap.xml"]


def test_empty_disallow_allows_everything():
    assert RobotsRules.parse("User-agent: *\nDisallow:\n").allowed("x", "/anything")


def test_normalize_url():
    assert normalize_url("example.com") == "https://example.com"
    assert normalize_url(" http://a.example/x ") == "http://a.example/x"
    with pytest.raises(FetchError):
        normalize_url("ftp://a.example")


def client(tmp_path, handler) -> HttpClient:
    return HttpClient(cache_dir=tmp_path, transport=httpx.MockTransport(handler), interval=0)


def fetch(tmp_path, handler, url="https://site.example/page", **kwargs):
    async def go():
        http = client(tmp_path, handler)
        try:
            return await http.get(url, **kwargs)
        finally:
            await http.aclose()

    return asyncio.run(go())


def test_robots_disallow_raises_with_hint(tmp_path):
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /page")
        return httpx.Response(200, text="ok")

    with pytest.raises(RobotsDisallowed) as info:
        fetch(tmp_path, handler, robots=True)
    assert "--ignore-robots" in (info.value.hint or "")
    assert fetch(tmp_path, handler, robots=False).text == "ok"


@pytest.mark.parametrize(("status", "allowed"), [(404, True), (403, True), (503, False)])
def test_robots_status_handling_follows_rfc_9309(tmp_path, status, allowed):
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(status, headers={"retry-after": "0"})
        return httpx.Response(200, text="ok")

    if allowed:
        assert fetch(tmp_path, handler, robots=True).status == 200
    else:
        with pytest.raises(RobotsDisallowed, match="HTTP 503"):
            fetch(tmp_path, handler, robots=True)


def test_retries_on_503_with_retry_after(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) < 3:
            return httpx.Response(503, headers={"retry-after": "0"})
        return httpx.Response(200, text="finally")

    assert fetch(tmp_path, handler).text == "finally"
    assert len(calls) == 3


def test_http_errors_become_readable(tmp_path):
    with pytest.raises(FetchError, match="HTTP 404") as info:
        fetch(tmp_path, lambda r: httpx.Response(404))
    assert info.value.hint == "check the URL"
    with pytest.raises(FetchError, match="HTTP 403") as info:
        fetch(tmp_path, lambda r: httpx.Response(403))
    assert "does not try to get around blocks" in (info.value.hint or "")


def test_connection_errors_are_retried_then_reported(tmp_path):
    def handler(request):
        raise httpx.ConnectError("[Errno -2] Name or service not known")

    with pytest.raises(FetchError, match="could not connect"):
        fetch(tmp_path, handler, retries=0)


def test_conditional_requests_reuse_the_cached_body(tmp_path):
    seen_headers = []

    def handler(request):
        seen_headers.append(dict(request.headers))
        if request.headers.get("if-none-match") == '"v1"':
            return httpx.Response(304)
        return httpx.Response(200, text="body v1", headers={"etag": '"v1"'})

    first = fetch(tmp_path, handler)
    second = fetch(tmp_path, handler)
    assert not first.from_cache
    assert second.from_cache
    assert second.text == "body v1"
    assert seen_headers[1]["if-none-match"] == '"v1"'
    third = fetch(tmp_path, handler, cache=False)
    assert "if-none-match" not in seen_headers[2] and not third.from_cache


def test_size_limit(tmp_path):
    with pytest.raises(FetchError, match="is over 1 MB"):
        fetch(
            tmp_path, lambda r: httpx.Response(200, content=b"x" * 3_000_000), max_bytes=1_000_000
        )


def test_user_agent_identifies_the_project(tmp_path):
    agents = []

    def handler(request):
        agents.append(request.headers["user-agent"])
        return httpx.Response(200)

    fetch(tmp_path, handler)
    fetch(tmp_path, handler, user_agent="MyBot/1.0 (me@example.com)")
    assert agents[0].startswith("UnlimitedPipe/")
    assert agents[1] == "MyBot/1.0 (me@example.com)"


def test_per_host_rate_limit(tmp_path):
    async def go():
        http = HttpClient(
            cache_dir=tmp_path,
            transport=httpx.MockTransport(lambda r: httpx.Response(200)),
            interval=0.2,
        )
        loop = asyncio.get_running_loop()
        start = loop.time()
        await asyncio.gather(
            *(http.get(f"https://a.example/{i}") for i in range(3)), http.get("https://b.example/")
        )
        await http.aclose()
        return loop.time() - start

    elapsed = asyncio.run(go())
    assert 0.38 <= elapsed < 1.5


def test_unreachable_host_is_not_blamed_on_robots(tmp_path):
    def handler(request):
        raise httpx.ConnectError("[Errno -2] Name or service not known")

    with pytest.raises(FetchError) as info:
        fetch(tmp_path, handler, robots=True, retries=0)
    assert not isinstance(info.value, RobotsDisallowed)
    assert "could not connect" in info.value.message
