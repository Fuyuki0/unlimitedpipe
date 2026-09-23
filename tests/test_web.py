import json

import pytest

from tests.conftest import fixture, run_source
from unlimitedpipe.sources.web import Web, parse_field_spec
from unlimitedpipe.structured import parse_price

SITE = "https://acme.example"


def test_document_event(web, ctx):
    web.add(f"{SITE}/pricing", fixture("article.html"))
    [event] = run_source(Web(url=[f"{SITE}/pricing"]), ctx)
    d = event.data
    assert event.type == "document"
    assert event.key == event.source_url == f"{SITE}/pricing"
    assert d["title"] == "Pricing | Acme"
    assert d["description"] == "Simple pricing for teams."
    assert d["canonical"] == f"{SITE}/pricing"
    assert d["lang"] == "en"
    assert d["feeds"] == [f"{SITE}/blog/feed.xml"]
    assert d["structured"] == ["Organization"]
    assert {"level": 2, "text": "Pro"} in d["headings"]
    assert "Plans for every team." in d["text"]
    for hidden in ("tracking", "Secret banner", "Also hidden", "display:none"):
        assert hidden not in d["text"]
    assert "links" not in d and "tables" not in d
    assert event.timestamp == "2026-09-01T10:00:00Z"
    assert event.metadata["status"] == 200
    assert event.metadata["method"] == "html"


def test_links_tables_and_meta_on_request(web, ctx):
    web.add(f"{SITE}/pricing", fixture("article.html"))
    [event] = run_source(
        Web(url=[f"{SITE}/pricing"], links=True, tables=True, metadata=True, text=False), ctx
    )
    d = event.data
    assert [link["url"] for link in d["links"]] == [
        f"{SITE}/basic",
        f"{SITE}/pro",
        "https://other.example/x",
    ]
    assert d["tables"][0]["rows"] == [
        {"Feature": "Seats", "Basic": "1", "Pro": "10"},
        {"Feature": "Support", "Basic": "Email", "Pro": "24/7"},
    ]
    assert d["meta"]["og:title"] == "Acme pricing"
    assert "text" not in d


def test_scheme_is_added(web, ctx):
    web.add("https://acme.example", "<title>Home</title>")
    [event] = run_source(Web(url=["acme.example"]), ctx)
    assert event.data["title"] == "Home"


def test_json_ld_products_one_event_per_offer(web, ctx):
    web.add(f"{SITE}/shoe", fixture("product-jsonld.html"))
    events = run_source(Web(url=[f"{SITE}/shoe"]), ctx)
    assert [e.type for e in events] == ["product"] * 3
    size9, size10, card = (e.data for e in events)
    assert size9["name"] == "Trail Shoe - Size 9"
    assert size9["price"] == 89.0 and size9["currency"] == "USD"
    assert size9["availability"] == "InStock"
    assert size9["brand"] == "Acme" and size9["rating"] == 4.6 and size9["reviews"] == 128
    assert size10["price"] == 1299.0 and size10["availability"] == "OutOfStock"
    assert events[0].key == f"{SITE}/shoe#TS-1-9"
    assert card["name"] == "Gift Card" and card["price"] == 10 and card["price_high"] == 100
    assert events[0].metadata["method"] == "json-ld"


def test_opengraph_product(web, ctx):
    web.add(f"{SITE}/mug", fixture("product-og.html"))
    [event] = run_source(Web(url=[f"{SITE}/mug"]), ctx)
    assert event.type == "product"
    assert event.data["name"] == "Blue Mug"
    assert event.data["price"] == 12.5 and event.data["currency"] == "EUR"
    assert event.metadata["method"] == "opengraph"


def test_shopify_variants_from_product_json(web, ctx):
    web.add(f"{SITE}/products/wool-runner?variant=11", fixture("shopify.html"))
    web.add(
        f"{SITE}/products/wool-runner.js",
        fixture("shopify-product.js"),
        content_type="application/json",
    )
    events = run_source(Web(url=[f"{SITE}/products/wool-runner?variant=11"]), ctx)
    assert [e.data["name"] for e in events] == ["Wool Runner - 8", "Wool Runner - 9"]
    first, second = (e.data for e in events)
    assert first["price"] == 3500.0 and first["compare_at_price"] == 4200.0
    assert first["currency"] == "THB" and first["availability"] == "InStock"
    assert first["image"] == "https://cdn.shopify.com/wool.jpg"
    assert second["sku"] == "12" and second["availability"] == "OutOfStock"
    assert events[0].metadata["method"] == "shopify"


def test_shopify_falls_back_when_product_json_is_unavailable(web, ctx):
    web.add(f"{SITE}/products/wool-runner", fixture("shopify.html"))
    [event] = run_source(Web(url=[f"{SITE}/products/wool-runner"]), ctx)
    assert event.type == "document"


def test_emit_document_skips_product_detection(web, ctx):
    web.add(f"{SITE}/shoe", fixture("product-jsonld.html"))
    [event] = run_source(Web(url=[f"{SITE}/shoe"], emit="document"), ctx)
    assert event.type == "document"
    assert event.data["structured"] == ["BreadcrumbList", "Product"]


def test_selector_emits_elements(web, make_ctx):
    web.add(f"{SITE}/pricing", fixture("article.html"))
    events = run_source(Web(url=[f"{SITE}/pricing"], selector=[".price", ".nothing"]), make_ctx())
    assert [e.data["text"] for e in events] == ["$9", "$49"]
    assert events[1].key == f"{SITE}/pricing#.price@1"
    assert events[1].data["attrs"] == {"class": "price", "data-amount": "49"}


def test_fields_with_each_build_records(web, ctx):
    web.add(f"{SITE}/pricing", fixture("article.html"))
    source = Web(
        url=[f"{SITE}/pricing"],
        each=".plan",
        field=["name=.plan-name", "price=.price@data-amount", "link=a.more@href"],
    )
    events = run_source(source, ctx)
    assert [e.data for e in events] == [
        {"name": "Basic", "price": "9", "link": f"{SITE}/basic"},
        {"name": "Pro", "price": "49", "link": f"{SITE}/pro"},
    ]
    assert events[0].label == "Basic"


def test_fields_without_each_make_one_record_with_lists(web, ctx):
    web.add(f"{SITE}/pricing", fixture("article.html"))
    [event] = run_source(Web(url=[f"{SITE}/pricing"], field=["plans=.plan-name", "title=h1"]), ctx)
    assert event.data == {"plans": ["Basic", "Pro"], "title": "Pricing"}


def test_emit_links(web, ctx):
    web.add(f"{SITE}/pricing", fixture("article.html"))
    events = run_source(Web(url=[f"{SITE}/pricing"], emit="links"), ctx)
    assert [e.key for e in events] == [f"{SITE}/basic", f"{SITE}/pro", "https://other.example/x"]
    assert events[0].type == "link" and events[0].data["page"] == f"{SITE}/pricing"


def test_json_responses_become_records(web, ctx):
    web.add(f"{SITE}/api", json.dumps([{"id": 1}, {"id": 2}]), content_type="application/json")
    events = run_source(Web(url=[f"{SITE}/api"]), ctx)
    assert [e.data for e in events] == [{"id": 1}, {"id": 2}]


def test_robots_and_errors_do_not_stop_other_urls(web, make_ctx):
    web.add(f"{SITE}/robots.txt", "User-agent: *\nDisallow: /secret", content_type="text/plain")
    web.add(f"{SITE}/ok", "<title>OK</title>")
    ctx = make_ctx()
    events = run_source(Web(url=[f"{SITE}/secret", f"{SITE}/missing", f"{SITE}/ok"]), ctx)
    assert [e.data["title"] for e in events] == ["OK"]
    assert ctx.failures == 2

    ctx = make_ctx(errors_as_events=True)
    events = run_source(Web(url=[f"{SITE}/secret", f"{SITE}/ok"]), ctx)
    assert [e.type for e in events] == ["error", "document"]
    assert "robots.txt" in events[0].data["error"]
    assert ctx.failures == 0

    web.add(f"{SITE}/secret", "<title>Secret</title>")
    [event] = run_source(Web(url=[f"{SITE}/secret"], ignore_robots=True), make_ctx())
    assert event.type == "document"


def test_urls_can_be_piped_in(web, make_ctx):
    from tests.conftest import _aiter, ev

    web.add(f"{SITE}/a", "<title>A</title>")
    web.add(f"{SITE}/b", "<title>B</title>")
    piped = _aiter([ev({"value": f"{SITE}/a"}), ev({"url": f"{SITE}/b", "text": "B"})])
    events = run_source(Web(), make_ctx(input=piped))
    assert [e.data["title"] for e in events] == ["A", "B"]


def test_invalid_options():
    with pytest.raises(ValueError, match="--each needs"):
        Web(url=["x"], each=".plan")
    with pytest.raises(ValueError, match="either --selector or --field"):
        Web(url=["x"], selector=["a"], field=["a=b"])
    with pytest.raises(ValueError, match="NAME=CSS"):
        parse_field_spec("price")
    with pytest.raises(ValueError, match="given twice"):
        Web(url=["x"], field=["a=b", "a=c"])


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("89", 89),
        ("89.00", 89.0),
        ("$1,299.00", 1299.0),
        ("1.299,00 €", 1299.0),
        ("฿1,299", 1299),
        ("12,50", 12.5),
        ("-5", -5),
        ("free", None),
        ("", None),
        (7.5, 7.5),
        (None, None),
    ],
)
def test_parse_price(text, expected):
    assert parse_price(text) == expected
