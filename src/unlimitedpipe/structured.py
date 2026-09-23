"""Structured data that sites publish on purpose: JSON-LD, OpenGraph, Shopify product JSON.

These layers are more reliable than CSS selectors: sites keep them correct because search
engines and shopping feeds read them.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin, urlsplit, urlunsplit

if TYPE_CHECKING:
    from bs4 import BeautifulSoup

PRODUCT_TYPES = {"product", "productgroup", "individualproduct", "productmodel"}


def parse_price(value: Any) -> float | int | None:
    """Parse ``89``, ``"89.00"``, ``"$1,299.00"``, ``"1.299,00 €"`` or ``"฿1,299"``.

    A single separator followed by exactly three digits is a thousands separator.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    text = re.sub(r"[^\d.,-]", "", str(value))
    if not re.search(r"\d", text):
        return None
    last_dot, last_comma = text.rfind("."), text.rfind(",")
    if last_dot >= 0 and last_comma >= 0:
        decimal = "." if last_dot > last_comma else ","
        thousands = "," if decimal == "." else "."
        text = text.replace(thousands, "").replace(decimal, ".")
    elif last_comma >= 0 or last_dot >= 0:
        sep = "," if last_comma >= 0 else "."
        head, _, tail = text.rpartition(sep)
        if len(tail) == 3 and text.count(sep) >= 1 and head.replace(sep, "").lstrip("-").isdigit():
            text = text.replace(sep, "")
        else:
            text = text.replace(",", ".")
            if text.count(".") > 1:
                return None
    try:
        number = float(text)
    except ValueError:
        return None
    return int(number) if number.is_integer() and "." not in str(value) else number


def availability(value: Any) -> str | None:
    """``https://schema.org/InStock`` -> ``InStock``."""
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip().rstrip("/").rsplit("/", 1)[-1]


def _types(item: dict[str, Any]) -> set[str]:
    value = item.get("@type")
    values = value if isinstance(value, list) else [value]
    return {str(v).rsplit("/", 1)[-1].lower() for v in values if v}


def _first(value: Any) -> Any:
    return value[0] if isinstance(value, list) and value else value


def _text(value: Any) -> str | None:
    value = _first(value)
    if isinstance(value, dict):
        value = value.get("name") or value.get("@id") or value.get("url")
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text or None


def _load_json_ld(raw: str) -> Any:
    raw = raw.strip()
    raw = re.sub(r"^\s*<!--|-->\s*$", "", raw).strip().rstrip(";")
    try:
        return json.loads(raw)
    except ValueError:
        # Common publisher mistake: raw newlines/tabs inside strings.
        try:
            return json.loads(re.sub(r"[\r\n\t]+", " ", raw))
        except ValueError:
            return None


def json_ld(soup: BeautifulSoup) -> list[dict[str, Any]]:
    """All JSON-LD objects on the page, with ``@graph`` containers flattened."""
    items: list[dict[str, Any]] = []

    def collect(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                collect(item)
        elif isinstance(value, dict):
            if "@graph" in value:
                collect(value["@graph"])
            if "@type" in value:
                items.append(value)

    for script in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        collect(_load_json_ld(script.string or script.get_text() or ""))
    return items


def json_ld_types(items: list[dict[str, Any]]) -> list[str]:
    seen: dict[str, None] = {}
    for item in items:
        value = item.get("@type")
        for name in value if isinstance(value, list) else [value]:
            if name:
                seen[str(name).rsplit("/", 1)[-1]] = None
    return list(seen)


def _offers(product: dict[str, Any]) -> list[dict[str, Any]]:
    raw = product.get("offers")
    offers = raw if isinstance(raw, list) else [raw] if isinstance(raw, dict) else []
    flat: list[dict[str, Any]] = []
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        nested = offer.get("offers")
        if "aggregateoffer" in _types(offer) and isinstance(nested, list) and nested:
            flat.extend(o for o in nested if isinstance(o, dict))
        else:
            flat.append(offer)
    return flat


def products_from_json_ld(items: list[dict[str, Any]], page_url: str) -> list[dict[str, Any]]:
    """One normalized record per priced offer of every Product on the page."""
    records: list[dict[str, Any]] = []
    for item in items:
        if not _types(item) & PRODUCT_TYPES:
            continue
        variants = item.get("hasVariant")
        if isinstance(variants, list) and variants:
            group_name = _text(item.get("name"))
            for variant in variants:
                if isinstance(variant, dict):
                    variant = {**variant}
                    variant.setdefault("brand", item.get("brand"))
                    records.extend(_product_records(variant, page_url, group_name))
            continue
        records.extend(_product_records(item, page_url, None))
    return records


def _product_records(
    item: dict[str, Any], page_url: str, group: str | None
) -> list[dict[str, Any]]:
    base = {
        "name": _text(item.get("name")) or group,
        "brand": _text(item.get("brand")),
        "sku": _text(item.get("sku")) or _text(item.get("productID")),
        "gtin": _text(
            item.get("gtin13") or item.get("gtin12") or item.get("gtin") or item.get("gtin14")
        ),
        "url": urljoin(page_url, _text(item.get("url")) or page_url),
        "image": _text(item.get("image")),
        "description": _text(item.get("description")),
    }
    rating = item.get("aggregateRating")
    if isinstance(rating, dict):
        base["rating"] = parse_price(rating.get("ratingValue"))
        base["reviews"] = parse_price(rating.get("reviewCount") or rating.get("ratingCount"))
    offers = _offers(item)
    if not offers:
        return [{**base, "price": None, "currency": None, "availability": None}]
    records = []
    for offer in offers:
        spec = offer.get("priceSpecification")
        spec = _first(spec) if spec else {}
        price = offer.get("price", offer.get("lowPrice"))
        if price is None and isinstance(spec, dict):
            price = spec.get("price")
        record = {
            **base,
            "price": parse_price(price),
            "currency": _text(offer.get("priceCurrency"))
            or (_text(spec.get("priceCurrency")) if isinstance(spec, dict) else None),
            "availability": availability(offer.get("availability")),
        }
        if offer.get("highPrice") is not None:
            record["price_high"] = parse_price(offer.get("highPrice"))
        if offer.get("sku") and len(offers) > 1:
            record["sku"] = _text(offer.get("sku"))
        if len(offers) > 1 and _text(offer.get("name")):
            record["name"] = (
                f"{base['name']} - {_text(offer.get('name'))}"
                if base["name"]
                else _text(offer.get("name"))
            )
        if offer.get("url"):
            record["url"] = urljoin(page_url, _text(offer.get("url")) or page_url)
        records.append(record)
    return records


def meta_properties(soup: BeautifulSoup) -> dict[str, str]:
    """``<meta property|name=... content=...>`` as a dict (first value wins)."""
    found: dict[str, str] = {}
    for tag in soup.find_all("meta"):
        key = tag.get("property") or tag.get("name") or tag.get("itemprop")
        content = tag.get("content")
        if isinstance(key, str) and isinstance(content, str) and key.lower() not in found:
            found[key.lower()] = content.strip()
    return found


def product_from_opengraph(meta: dict[str, str], page_url: str) -> dict[str, Any] | None:
    amount = meta.get("product:price:amount") or meta.get("og:price:amount")
    if amount is None:
        return None
    return {
        "name": meta.get("og:title"),
        "brand": meta.get("product:brand"),
        "sku": meta.get("product:retailer_item_id"),
        "url": meta.get("og:url") or page_url,
        "image": meta.get("og:image"),
        "description": meta.get("og:description"),
        "price": parse_price(amount),
        "currency": meta.get("product:price:currency") or meta.get("og:price:currency"),
        "availability": availability(
            meta.get("product:availability") or meta.get("og:availability")
        ),
    }


_SHOPIFY_MARKERS = ("cdn.shopify.com", "Shopify.shop", "shopify-digital-wallet")
_SHOPIFY_PRODUCT = re.compile(r"/products/([^/?#]+)")


def is_shopify(html: str, headers: dict[str, str]) -> bool:
    if any(h in headers for h in ("x-shopid", "x-shopify-stage", "x-sorting-hat-shopid")):
        return True
    if "shopify" in headers.get("powered-by", "").lower():
        return True
    return any(marker in html for marker in _SHOPIFY_MARKERS)


def shopify_product_js_url(page_url: str) -> str | None:
    """``https://store.com/collections/x/products/shoe?variant=1`` -> ``.../products/shoe.js``."""
    parts = urlsplit(page_url)
    match = _SHOPIFY_PRODUCT.search(parts.path)
    if not match:
        return None
    handle = match.group(1).removesuffix(".js").removesuffix(".json")
    return urlunsplit((parts.scheme, parts.netloc, f"/products/{handle}.js", "", ""))


def shopify_currency(html: str) -> str | None:
    match = re.search(r'Shopify\.currency\s*=\s*\{[^}]*"active"\s*:\s*"([A-Z]{3})"', html)
    return match.group(1) if match else None


def products_from_shopify(
    product: dict[str, Any], page_url: str, currency: str | None
) -> list[dict[str, Any]]:
    """One record per variant from Shopify's public ``/products/<handle>.js`` (prices in cents)."""
    base_url = page_url.split("?")[0]
    title = product.get("title")
    variants = product.get("variants") or []
    image = _first(product.get("images"))
    if isinstance(image, str) and image.startswith("//"):
        image = "https:" + image
    records = []
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        variant_title = variant.get("title")
        name = (
            title if variant_title in (None, "", "Default Title") else f"{title} - {variant_title}"
        )
        cents = variant.get("price")
        compare = variant.get("compare_at_price")
        records.append(
            {
                "name": name,
                "brand": product.get("vendor"),
                "sku": variant.get("sku") or str(variant.get("id")),
                "variant_id": variant.get("id"),
                "url": f"{base_url}?variant={variant.get('id')}",
                "image": image,
                "price": round(cents / 100, 2)
                if isinstance(cents, (int, float))
                else parse_price(cents),
                "compare_at_price": round(compare / 100, 2)
                if isinstance(compare, (int, float))
                else None,
                "currency": currency,
                "availability": "InStock" if variant.get("available") else "OutOfStock",
            }
        )
    return records
