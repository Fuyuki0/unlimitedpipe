"""The ``inspect`` source: what a URL offers and the most reliable way to read it."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from unlimitedpipe._version import USER_AGENT
from unlimitedpipe.component import Source, arg, opt
from unlimitedpipe.context import Context
from unlimitedpipe.errors import FetchError
from unlimitedpipe.event import Event
from unlimitedpipe.sources import input_urls


def _check(name: str, ok: bool, detail: str, *, warn: bool = False) -> dict[str, Any]:
    return {"name": name, "ok": ok, "detail": detail, "warn": warn}


class Inspect(Source):
    """Report what a URL offers (robots.txt, feeds, JSON-LD, products, sitemap, JavaScript) and
    suggest the command that reads it most reliably."""

    name = "inspect"
    url: list[str] = arg("URLs to inspect (or piped in)", default_factory=list)
    timeout: float = opt("Seconds to wait for each response", default=20.0)
    user_agent: str | None = opt(
        "User-Agent header (default identifies UnlimitedPipe)", default=None
    )

    async def collect(self, ctx: Context):
        async for url in input_urls(self.url, ctx, command="inspect"):
            try:
                yield await self.inspect(url, ctx)
            except FetchError as exc:
                error = ctx.fail(exc, source=self.name, url=url)
                if error is not None:
                    yield error

    async def inspect(self, url: str, ctx: Context) -> Event:
        from unlimitedpipe import html, structured
        from unlimitedpipe.http import normalize_url

        url = normalize_url(url)
        http = ctx.http
        parts = urlsplit(url)
        agent = (self.user_agent or USER_AGENT).split("/")[0].split()[0].lower()
        rules = await http.robots(url, user_agent=self.user_agent)
        path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        allowed = rules.allowed(agent, path)
        checks = [
            _check(
                "robots.txt",
                allowed,
                "allowed" if allowed else rules.deny_reason or "disallows this path",
                warn=not allowed,
            )
        ]
        data: dict[str, Any] = {"url": url, "robots_allowed": allowed, "checks": checks}
        if not allowed:
            data["kind"] = "blocked"
            data["suggestions"] = [
                "The site asks automated clients not to fetch this page. Look for an official "
                "API or feed instead."
            ]
            return Event(source=self.name, type="inspection", source_url=url, key=url, data=data)

        response = await http.get(
            url, timeout=self.timeout, user_agent=self.user_agent, cache=False
        )
        page = response.final_url
        metadata = {
            "status": response.status,
            "content_type": response.content_type,
            "elapsed_ms": response.elapsed_ms,
        }
        data["final_url"] = page
        suggestions: list[str] = []
        if "json" in response.content_type:
            data["kind"] = "json"
            checks.append(_check("JSON", True, "the URL returns JSON"))
            suggestions.append(f"unlimited web {url}   # one record event per JSON item")
            data["suggestions"] = suggestions
            return Event(
                source=self.name,
                type="inspection",
                source_url=url,
                key=url,
                data=data,
                metadata=metadata,
            )
        head = response.content[:500].lower()
        if b"<rss" in head or b"<feed" in head:
            data["kind"] = "feed"
            checks.append(_check("Feed", True, "the URL is an RSS/Atom feed"))
            data["suggestions"] = [f"unlimited rss {url}"]
            return Event(
                source=self.name,
                type="inspection",
                source_url=url,
                key=url,
                data=data,
                metadata=metadata,
            )

        soup = html.parse(response.content, response.encoding)
        props = structured.meta_properties(soup)
        items = structured.json_ld(soup)
        types = structured.json_ld_types(items)
        products = structured.products_from_json_ld(items, page)
        og_product = structured.product_from_opengraph(props, page)
        shopify = structured.is_shopify(response.text, response.headers)
        shopify_js = structured.shopify_product_js_url(page) if shopify else None
        feeds = html.feeds(soup, page)
        text = html.visible_text(soup)
        js_required = html.looks_js_rendered(soup, text)
        sitemaps = rules.sitemaps or await self._sitemap(url, ctx)

        data["title"] = html.title(soup, props)
        checks.append(_check("JSON-LD", bool(types), ", ".join(types[:6]) or "none"))
        if shopify:
            checks.append(_check("Shopify", True, shopify_js or "store detected"))
        product_count = len(products) or (1 if og_product else 0)
        method = (
            "shopify"
            if shopify_js
            else "json-ld"
            if products
            else "opengraph"
            if og_product
            else None
        )
        checks.append(
            _check(
                "Products", bool(method), f"found (via {method})" if method else "no product data"
            )
        )
        og_type = props.get("og:type")
        checks.append(
            _check("OpenGraph", bool(og_type or props.get("og:title")), og_type or "none")
        )
        checks.append(_check("Feeds", bool(feeds), ", ".join(feeds[:3]) or "none advertised"))
        checks.append(_check("Sitemap", bool(sitemaps), ", ".join(sitemaps[:2]) or "none found"))
        words = len(text.split())
        checks.append(
            _check(
                "Readable HTML",
                not js_required,
                f"{words} words without JavaScript"
                if not js_required
                else f"only {words} words without JavaScript; the page likely renders in a browser",
                warn=js_required,
            )
        )

        if method:
            suggestions.append(f"unlimited web {url} | unlimited diff   # price and stock changes")
        if feeds:
            suggestions.append(f"unlimited rss {feeds[0]}")
        if js_required:
            suggestions.append(
                f"unlimited web {url} --browser   # render it first "
                '(pip install "unlimitedpipe[browser]" && playwright install chromium)'
            )
        elif not method:
            suggestions.append(f"unlimited web {url}")
            suggestions.append(f"unlimited web {url} --selector 'h2'   # pick exact elements")

        data.update(
            {
                "kind": "page",
                "json_ld_types": types,
                "products": product_count,
                "product_method": method,
                "platform": "shopify" if shopify else None,
                "feeds": feeds,
                "sitemaps": sitemaps,
                "js_required": js_required,
                "suggestions": suggestions,
            }
        )
        return Event(
            source=self.name,
            type="inspection",
            source_url=url,
            key=url,
            data=data,
            metadata=metadata,
        )

    async def _sitemap(self, url: str, ctx: Context) -> list[str]:
        parts = urlsplit(url)
        candidate = f"{parts.scheme}://{parts.netloc}/sitemap.xml"
        try:
            response = await ctx.http.get(
                candidate,
                timeout=self.timeout,
                user_agent=self.user_agent,
                robots=True,
                cache=False,
                raise_for_status=False,
                retries=0,
            )
        except FetchError:
            return []
        head = response.content[:2000]
        if response.status == 200 and (b"<urlset" in head or b"<sitemapindex" in head):
            return [candidate]
        return []
