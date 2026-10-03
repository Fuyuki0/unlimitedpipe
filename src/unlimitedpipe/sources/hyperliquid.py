"""Perpetual futures funding and open interest from Hyperliquid's public API."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from unlimitedpipe.component import Source, opt
from unlimitedpipe.context import Context
from unlimitedpipe.errors import FetchError
from unlimitedpipe.event import Event

INFO = "https://api.hyperliquid.xyz/info"
PAGE = "https://app.hyperliquid.xyz/trade/{coin}"


def markets(document: list[Any]) -> list[dict[str, Any]]:
    """Each perpetual market: its funding rate an hour, open interest in dollars, price and
    day's volume."""
    meta, contexts = document
    found = []
    for asset, ctx in zip(meta.get("universe") or [], contexts, strict=False):
        try:
            funding = float(ctx["funding"])
            price = float(ctx["markPx"])
            open_interest = float(ctx["openInterest"]) * price
            volume = float(ctx.get("dayNtlVlm") or 0)
            before = float(ctx.get("prevDayPx") or 0)
        except (KeyError, TypeError, ValueError):
            continue
        if asset.get("isDelisted"):
            continue
        found.append(
            {
                "coin": asset["name"],
                "funding": funding,
                "annual": funding * 24 * 365,
                "open_interest": open_interest,
                "price": price,
                "change": price / before - 1 if before else None,
                "volume": volume,
            }
        )
    return found


def funding_item(market: dict[str, Any], now: datetime) -> dict[str, Any]:
    from unlimitedpipe.expr import short_number

    coin, rate = market["coin"], market["funding"]
    payer = "longs pay shorts" if rate > 0 else "shorts pay longs"
    open_interest = short_number(market["open_interest"])
    title = (
        f"{coin} funding on Hyperliquid: {rate * 100:+.4f}% an hour "
        f"({market['annual'] * 100:+.0f}% a year), open interest ${open_interest}"
    )
    return {
        "title": title,
        "summary": f"On Hyperliquid's {coin} perpetual, {payer} {abs(rate) * 100:.4f}% an hour "
        f"({abs(market['annual']) * 100:.0f}% a year) at ${market['price']:,.6g}, with "
        f"${short_number(market['open_interest'])} of open interest and "
        f"${short_number(market['volume'])} traded in 24 hours. Data, not investment advice.",
        "link": PAGE.format(coin=coin),
        "published_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        **market,
    }


class Hyperliquid(Source):
    """Funding rates and open interest of Hyperliquid's perpetual futures, from its public API.

    `funding` lists the markets whose funding is at least --min-funding an hour either way
    (0.01% an hour is about 88% a year: crowded positions) with at least --min-open-interest
    dollars open; `--coin BTC --min-funding 0` lists one market's funding as it is.
    """

    name = "hyperliquid"
    examples = (
        "unlimited hyperliquid",
        "unlimited hyperliquid --coin BTC --coin ETH --min-funding 0",
    )

    min_funding: float = opt(
        "Only funding of at least this much an hour, either way (0.0001 is 0.01%)", default=0.0001
    )
    min_open_interest: float = opt("Only markets with this many dollars open", default=50e6)
    coin: list[str] = opt("Only these coins (repeatable)", default_factory=list, metavar="COIN")
    timeout: float = opt("Seconds to wait for Hyperliquid", default=20.0)

    async def collect(self, ctx: Context):
        try:
            response = await ctx.http.post(
                INFO, json_body={"type": "metaAndAssetCtxs"}, timeout=self.timeout, secret_url=False
            )
            found = markets(json.loads(response.text))
        except FetchError as exc:
            if (error := ctx.fail(exc, source=self.name, url=INFO)) is not None:
                yield error
            return
        except (ValueError, TypeError) as exc:
            ctx.warn(f"hyperliquid: the answer could not be read ({exc})")
            return
        wanted = {c.upper() for c in self.coin}
        now = datetime.now(UTC)
        for market in sorted(found, key=lambda m: -abs(m["funding"])):
            if wanted and market["coin"].upper() not in wanted:
                continue
            if abs(market["funding"]) < self.min_funding:
                continue
            if market["open_interest"] < self.min_open_interest:
                continue
            item = funding_item(market, now)
            yield Event(
                source=self.name,
                type="funding",
                source_url=item["link"],
                key=f"{market['coin']}:{now:%Y-%m-%d}",
                timestamp=item["published_at"],
                data=item,
                metadata={"method": "hyperliquid-info"},
            )
