"""The ``web`` source: fetch pages and emit what they contain."""

from __future__ import annotations

import logging
import re
from typing import Any, Literal

from unlimitedpipe.component import Source, arg, opt
from unlimitedpipe.context import Context
from unlimitedpipe.errors import FetchError
from unlimitedpipe.event import Event
from unlimitedpipe.sources import input_urls

log = logging.getLogger("unlimitedpipe.web")


def parse_field_spec(spec: str) -> tuple[str, str, str | None]:
    """``price=.price`` -> (price, .price, None); ``link=a.more@href`` -> (link, a.more, href)."""
    name, sep, rest = spec.partition("=")
    if not sep or not name.strip() or not rest.strip():
        raise ValueError(f"invalid --field {spec!r}; use NAME=CSS or NAME=CSS@attribute")
    selector, attribute = rest.strip(), None
    match = re.fullmatch(r"(.+?)@([\w:.-]+)", selector)
    if match:
        selector, attribute = match.group(1).strip(), match.group(2)
    return name.strip(), selector, attribute


class Web(Source):
    """Fetch web pages and emit what they contain.

    By default each page becomes one ``document`` event (title, description, headings, text,
    feeds, structured-data types). Pages that publish product data (Shopify, JSON-LD,
    OpenGraph) become one ``product`` event per offer instead, so ``| unlimited diff`` reports
    price and stock changes. ``--selector`` and ``--field`` extract exactly what you point at.
    Respects robots.txt and rate-limits each host.
    """

    name = "web"
    url: list[str] = arg("Page URLs (or piped in, one per line)", default_factory=list)
    selector: list[str] = opt(
        "Emit one `element` event per match of this CSS selector",
        short="-s",
        metavar="CSS",
        default_factory=list,
    )
    field: list[str] = opt(
        "Extract NAME=CSS or NAME=CSS@attr into one `record` (repeatable)",
        short="-f",
        metavar="NAME=CSS",
        default_factory=list,
    )
    each: str | None = opt(
        "With --field: one record per element matching this selector", metavar="CSS", default=None
    )
    emit: Literal["auto", "document", "products", "links"] = opt(
        "What to emit without --selector/--field", default="auto"
    )
    links: bool = opt("Include the page's links in document events", default=False)
    tables: bool = opt("Include tables in document events", default=False)
    metadata: bool = opt("Include all <meta> tags in document events", default=False)
    text: bool = opt("Include visible text in document events", default=True)
    timeout: float = opt("Seconds to wait for each response", default=20.0)
    user_agent: str | None = opt(
        "User-Agent header (default identifies UnlimitedPipe)", default=None
    )
    ignore_robots: bool = opt(
        "Skip robots.txt (only with the site owner's permission)", default=False
    )
    cache: bool = opt("Revalidate unchanged pages with ETag/Last-Modified", default=True)
    records: str | None = opt(
        "For JSON responses: path to the list of records, e.g. `data.items`",
        default=None,
        metavar="PATH",
    )

    def __post_init__(self) -> None:
        self._fields = [parse_field_spec(spec) for spec in self.field]
        names = [name for name, _, _ in self._fields]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"--field {duplicates[0]!r} is given twice")
        if self.each and not self._fields:
            raise ValueError("--each needs at least one --field NAME=CSS")
        if self._fields and self.selector:
            raise ValueError("use either --selector or --field, not both")
        if self.timeout <= 0:
            raise ValueError("--timeout must be positive")

    async def collect(self, ctx: Context):
        async for url in input_urls(self.url, ctx, command="web"):
            try:
                events = await self.fetch(url, ctx)
            except (FetchError, ValueError) as exc:
                error = ctx.fail(exc, source=self.name, url=url)
                if error is not None:
                    yield error
                continue
            for event in events:
                yield event

    async def _get(self, url: str, ctx: Context):
        return await ctx.http.get(
            url,
            timeout=self.timeout,
            user_agent=self.user_agent,
            robots=not self.ignore_robots,
            cache=self.cache,
        )

    async def fetch(self, url: str, ctx: Context) -> list[Event]:
        from unlimitedpipe import html
        from unlimitedpipe.http import normalize_url

        url = normalize_url(url)
        response = await self._get(url, ctx)
        page = response.final_url
        meta = {
            "status": response.status,
            "final_url": page,
            "content_type": response.content_type,
            "elapsed_ms": response.elapsed_ms,
            "not_modified": response.from_cache,
        }

        if "json" in response.content_type:
            value = response.json()
            if self.records:
                from unlimitedpipe.fields import MISSING, get_path, split_path

                value = get_path(value, split_path(self.records))
                if value is MISSING:
                    raise FetchError(f"{url}: the JSON has no field {self.records!r}", url=url)
            return self._json_records(url, value, meta)
        if response.content_type and not any(
            t in response.content_type for t in ("html", "xml", "text/plain")
        ):
            raise FetchError(
                f"{url} is {response.content_type}, not a web page",
                url=url,
                hint="UnlimitedPipe reads HTML pages, feeds (unlimited rss) and JSON",
            )
        head = response.content[:500].lstrip().lower()
        if b"<rss" in head or b"<feed" in head:
            ctx.warn(f"{url} is a feed; `unlimited rss {url}` emits one event per item")

        soup = html.parse(response.content, response.encoding)
        if self.selector:
            return self._elements(url, page, soup, meta, ctx)
        if self._fields:
            return self._records(url, page, soup, meta, ctx)
        if self.emit == "links":
            return [
                Event(
                    source=self.name,
                    type="link",
                    source_url=url,
                    key=link["url"],
                    data={**link, "page": page},
                    metadata={**meta, "method": "html"},
                )
                for link in html.links(soup, page)
            ]
        if self.emit in ("auto", "products"):
            products, method = await self._products(url, response, soup, ctx)
            if products:
                return [
                    self._product_event(url, record, {**meta, "method": method})
                    for record in products
                ]
            if self.emit == "products":
                ctx.warn(f"no product data found on {url}")
                return []
        return [self._document(url, page, soup, meta)]

    def _json_records(self, url: str, value: Any, meta: dict[str, Any]) -> list[Event]:
        items = value if isinstance(value, list) else [value]
        return [
            Event(
                source=self.name,
                type="record",
                source_url=url,
                data=item if isinstance(item, dict) else {"value": item},
                metadata={**meta, "method": "json"},
            )
            for item in items
        ]

    async def _products(
        self, url: str, response, soup, ctx: Context
    ) -> tuple[list[dict[str, Any]], str]:
        from unlimitedpipe import structured

        text = response.text
        items = structured.json_ld(soup)
        meta = structured.meta_properties(soup)
        from_ld = structured.products_from_json_ld(items, response.final_url)
        from_og = structured.product_from_opengraph(meta, response.final_url)

        if structured.is_shopify(text, response.headers):
            js_url = structured.shopify_product_js_url(response.final_url)
            if js_url:
                try:
                    product = (await self._get(js_url, ctx)).json()
                except FetchError as exc:
                    log.debug("shopify product JSON unavailable for %s: %s", url, exc.message)
                else:
                    currency = (
                        structured.shopify_currency(text)
                        or next((r["currency"] for r in from_ld if r.get("currency")), None)
                        or (from_og or {}).get("currency")
                    )
                    records = structured.products_from_shopify(
                        product, response.final_url, currency
                    )
                    if records:
                        return records, "shopify"
        if from_ld:
            return from_ld, "json-ld"
        if from_og:
            return [from_og], "opengraph"
        return [], ""

    def _product_event(self, url: str, record: dict[str, Any], meta: dict[str, Any]) -> Event:
        key = record.get("url") or url
        if record.get("sku"):
            key = f"{key}#{record['sku']}"
        return Event(
            source=self.name, type="product", source_url=url, key=key, data=record, metadata=meta
        )

    def _document(self, url: str, page: str, soup, meta: dict[str, Any]) -> Event:
        from unlimitedpipe import html, structured

        props = structured.meta_properties(soup)
        items = structured.json_ld(soup)
        text = html.visible_text(soup)
        data: dict[str, Any] = {
            "url": page,
            "title": html.title(soup, props),
            "description": props.get("description") or props.get("og:description"),
            "canonical": html.canonical(soup, page),
            "lang": html.lang(soup),
            "headings": html.headings(soup),
            "word_count": len(text.split()),
            "feeds": html.feeds(soup, page),
            "structured": structured.json_ld_types(items),
        }
        if self.text:
            data["text"] = text
        if self.links:
            data["links"] = html.links(soup, page)
        if self.tables:
            data["tables"] = html.tables(soup)
        if self.metadata:
            data["meta"] = props
        published = props.get("article:modified_time") or props.get("article:published_time")
        return Event(
            source=self.name,
            type="document",
            source_url=url,
            key=url,
            timestamp=published,
            data=data,
            metadata={**meta, "method": "html"},
        )

    def _elements(
        self, url: str, page: str, soup, meta: dict[str, Any], ctx: Context
    ) -> list[Event]:
        from unlimitedpipe import html

        events = []
        for selector in self.selector:
            nodes = html.select(soup, selector)
            if not nodes:
                ctx.warn(f"{selector!r} matched nothing on {url}")
            for index, node in enumerate(nodes):
                events.append(
                    Event(
                        source=self.name,
                        type="element",
                        source_url=url,
                        key=f"{url}#{selector}@{index}",
                        data={
                            "selector": selector,
                            "index": index,
                            **html.element_data(node, page),
                        },
                        metadata={**meta, "method": "css"},
                    )
                )
        return events

    def _records(
        self, url: str, page: str, soup, meta: dict[str, Any], ctx: Context
    ) -> list[Event]:
        from unlimitedpipe import html

        def extract(scope) -> dict[str, Any]:
            record: dict[str, Any] = {}
            for name, selector, attribute in self._fields:
                values = [
                    html.element_value(n, attribute, page) for n in html.select(scope, selector)
                ]
                values = [v for v in values if v is not None]
                record[name] = values[0] if len(values) == 1 else (values or None)
            return record

        if self.each:
            scopes = html.select(soup, self.each)
            if not scopes:
                ctx.warn(f"--each {self.each!r} matched nothing on {url}")
            keyed = [(f"{url}#{self.each}@{i}", scope) for i, scope in enumerate(scopes)]
        else:
            keyed = [(url, soup)]
        events = []
        for key, scope in keyed:
            record = extract(scope)
            if not any(v is not None for v in record.values()):
                ctx.warn(f"no --field matched on {url}" + (f" in {key}" if self.each else ""))
            events.append(
                Event(
                    source=self.name,
                    type="record",
                    source_url=url,
                    key=key,
                    data=record,
                    metadata={**meta, "method": "css"},
                )
            )
        return events
