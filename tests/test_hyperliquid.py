from datetime import UTC, datetime

from unlimitedpipe.sources.hyperliquid import funding_item, markets

DOC = [
    {"universe": [{"name": "BTC"}, {"name": "MON"}, {"name": "OLD", "isDelisted": True}]},
    [
        {
            "funding": "0.0000072",
            "openInterest": "36980",
            "markPx": "84557",
            "prevDayPx": "84000",
            "dayNtlVlm": "532900000",
        },
        {
            "funding": "0.000106",
            "openInterest": "1000000000",
            "markPx": "0.0629",
            "prevDayPx": "0.06",
            "dayNtlVlm": "1000000",
        },
        {"funding": "0.01", "openInterest": "1", "markPx": "1", "prevDayPx": "1", "dayNtlVlm": "0"},
    ],
]


def test_funding_reads_as_who_pays_whom():
    btc, mon = markets(DOC)  # the delisted market is left out
    assert round(btc["open_interest"]) == round(36980 * 84557)
    item = funding_item(mon, datetime(2026, 10, 4, tzinfo=UTC))
    assert item["title"] == (
        "MON funding on Hyperliquid: +0.0106% an hour (+93% a year), open interest $62.9M"
    )
    assert "longs pay shorts 0.0106% an hour" in item["summary"]
