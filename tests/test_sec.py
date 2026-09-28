import pytest

from tests.conftest import run_source
from unlimitedpipe.errors import UsageError
from unlimitedpipe.sources.sec import Sec, headline, parse_form4, person_name, summarize

LATEST = (
    "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=4&owner=include"
    "&count=100&start=0&output=atom"
)
FOLDER = "https://www.sec.gov/Archives/edgar/data"


def entry(title: str, link: str) -> str:
    return (
        f"<entry><title>{title}</title><link rel='alternate' type='text/html' href='{link}'/>"
        "<updated>2026-09-25T16:05:00-04:00</updated><id>x</id></entry>"
    )


ATOM = (
    "<?xml version='1.0' encoding='ISO-8859-1'?><feed xmlns='http://www.w3.org/2005/Atom'>"
    "<title>Latest Filings</title>"
    + entry(
        "4 - HUANG JEN HSUN (0001197649) (Reporting)",
        f"{FOLDER}/1197649/0001-26-7/0001-26-7-index.htm",
    )
    + entry(
        "4 - NVIDIA CORP (0001045810) (Issuer)", f"{FOLDER}/1045810/0001-26-7/0001-26-7-index.htm"
    )
    + entry(
        "424B2 - BANK OF MONTREAL (0000927971) (Filer)",
        f"{FOLDER}/927971/0002-26-1/0002-26-1-index.htm",
    )
    + "</feed>"
)

FORM4 = b"""<SEC-DOCUMENT>
<TYPE>4
<XML>
<?xml version="1.0"?>
<ownershipDocument>
  <issuer><issuerName>NVIDIA CORP /DE/</issuerName>
    <issuerTradingSymbol>nvda</issuerTradingSymbol></issuer>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>HUANG JEN HSUN</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship>
      <isDirector>1</isDirector><isOfficer>1</isOfficer>
      <officerTitle>President and CEO</officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>
  <aff10b5One>1</aff10b5One>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-09-24</value></transactionDate>
      <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>60000</value></transactionShares>
        <transactionPricePerShare><value>180</value></transactionPricePerShare>
      </transactionAmounts>
      <postTransactionAmounts><sharesOwnedFollowingTransaction><value>800000</value>
      </sharesOwnedFollowingTransaction></postTransactionAmounts>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-09-23</value></transactionDate>
      <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>40000</value></transactionShares>
        <transactionPricePerShare><value>185</value></transactionPricePerShare>
      </transactionAmounts>
      <postTransactionAmounts><sharesOwnedFollowingTransaction><value>760000</value>
      </sharesOwnedFollowingTransaction></postTransactionAmounts>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-09-23</value></transactionDate>
      <transactionCoding><transactionCode>F</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>500</value></transactionShares>
        <transactionPricePerShare><value>185</value></transactionPricePerShare>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>
</XML>
</SEC-DOCUMENT>"""


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("HUANG JEN HSUN", "Jen Hsun Huang"),
        ("SMITH FREDERICK G", "Frederick G Smith"),
        ("Berkshire Hathaway Inc", "Berkshire Hathaway Inc"),
        ("AJB CAPITAL, LLC", "AJB Capital, LLC"),
        ("MUSK", "Musk"),
    ],
)
def test_person_name(raw, expected):
    assert person_name(raw) == expected


def test_a_form4_becomes_one_trade_per_transaction_code():
    body = FORM4[FORM4.index(b"<?xml") : FORM4.index(b"</XML>")]
    filing = parse_form4(body)
    assert filing["ticker"] == "NVDA" and filing["role"] == "President and CEO, director"
    assert filing["planned"] is True
    sale = summarize(filing, "S")
    assert sale is not None
    assert sale["shares"] == 100000 and sale["value"] == 60000 * 180 + 40000 * 185
    assert sale["price"] == 182.0 and sale["shares_after"] == 760000
    assert sale["traded_on"] == "2026-09-23"
    assert summarize(filing, "P") is None
    trade = {**filing, **sale}
    assert headline(trade) == (
        "Nvidia Corp (NVDA): Jen Hsun Huang (President and CEO, director) "
        "sold 100,000 shares at $182.00 ($18.2M)"
    )


def test_a_total_filed_as_the_price_a_share_is_not_multiplied_again():
    filing = {
        "transactions": [
            {
                "code": "P",
                "date": "2025-10-17",
                "shares": 25_000_000.0,
                "price": 13_000_000.0,
                "shares_after": None,
            }
        ],
        "issuer": "Kayne Anderson Energy Infrastructure Fund, Inc.",
        "ticker": "KYN",
        "owner": "MetLife Investment Management LLC",
        "role": "10% owner",
    }
    trade = summarize(filing, "P")
    assert trade is not None and trade["value"] is None and trade["filed_price"] == 13_000_000
    assert headline({**filing, **trade}).endswith(
        "bought 25,000,000 shares (filed price $13,000,000.00 a share, not plausible)"
    )


def test_insider_trades_reads_each_filing_once_and_skips_other_forms(web, make_ctx):
    web.add(LATEST, ATOM, content_type="application/atom+xml")
    web.add(f"{FOLDER}/1197649/0001-26-7/0001-26-7.txt", FORM4, content_type="text/plain")
    events = run_source(Sec(resource="insider-trades", contact="me@example.com"), make_ctx())
    assert [e.key for e in events] == ["0001-26-7#S"]  # F (tax withholding) is not kept
    [trade] = events
    assert trade.type == "insider-trade" and trade.data["action"] == "sold"
    assert trade.source_url.endswith("0001-26-7-index.htm")
    assert trade.timestamp == "2026-09-25T16:05:00-04:00"
    agents = {r.headers["user-agent"] for r in web.requests}
    assert agents == {f"UnlimitedPipe/{__import__('unlimitedpipe').__version__} me@example.com"}
    assert all("424B2" not in u and "927971" not in u for u in web.urls())


def test_insider_trades_filters_by_code_and_value(web, make_ctx):
    web.add(LATEST, ATOM, content_type="application/atom+xml")
    web.add(f"{FOLDER}/1197649/0001-26-7/0001-26-7.txt", FORM4, content_type="text/plain")
    kept = run_source(
        Sec(resource="insider-trades", contact="me@example.com", code=["f", "s"]), make_ctx()
    )
    assert [e.data["code"] for e in kept] == ["F", "S"]
    big = run_source(
        Sec(resource="insider-trades", contact="me@example.com", min_value=20_000_000),
        make_ctx(),
    )
    assert big == []


def test_all_new_reads_each_filing_once_across_runs(web, make_ctx):
    web.add(LATEST, ATOM, content_type="application/atom+xml")
    web.add(f"{FOLDER}/1197649/0001-26-7/0001-26-7.txt", FORM4, content_type="text/plain")
    source = Sec(resource="insider-trades", contact="me@example.com", all_new=True, limit=500)
    assert [e.key for e in run_source(source, make_ctx())] == ["0001-26-7#S"]
    texts = [u for u in web.urls() if u.endswith(".txt")]
    assert run_source(source, make_ctx()) == []  # nothing filed since: nothing read again
    assert [u for u in web.urls() if u.endswith(".txt")] == texts
    with pytest.raises(ValueError, match="between 1 and 200"):
        Sec(resource="insider-trades", limit=500)


def test_the_sec_needs_a_contact_email(make_ctx, monkeypatch):
    monkeypatch.delenv("SEC_CONTACT", raising=False)
    with pytest.raises(UsageError, match="contact email"):
        run_source(Sec(resource="insider-trades"), make_ctx())
    with pytest.raises(ValueError, match="unknown transaction code"):
        Sec(resource="insider-trades", code=["Z"])


def test_stakes_join_the_company_and_its_investors():
    from unlimitedpipe.sources.sec import stakes

    folder = "https://www.sec.gov/Archives/edgar/data"
    entries = [
        {
            "title": "SCHEDULE 13D - ORBIMED ADVISORS LLC (0001055951) (Filed by)",
            "link": f"{folder}/1055951/000094787126000898/0000947871-26-000898-index.htm",
            "updated": "2026-09-25T17:11:02-04:00",
        },
        {
            "title": "SCHEDULE 13D - Electra Therapeutics, Inc. (0002088082) (Subject)",
            "link": f"{folder}/2088082/000094787126000898/0000947871-26-000898-index.htm",
            "updated": "2026-09-25T17:11:02-04:00",
        },
        {
            "title": "SCHEDULE 13D/A - JEWETT CAMERON TRADING CO LTD (0000885307) (Subject)",
            "link": f"{folder}/885307/000153658826000035/0001536588-26-000035-index.htm",
        },
        {"title": "4 - Someone (0000000001) (Reporting)", "link": f"{folder}/1/2/3-index.htm"},
    ]
    new, amended = stakes(entries)
    assert new["title"] == (
        "Electra Therapeutics, Inc.: Orbimed Advisors LLC disclosed a stake of 5% or more "
        "(Schedule 13D)"
    )
    assert new["link"].startswith(f"{folder}/2088082/") and not new["amendment"]
    assert amended["title"].startswith("Jewett Cameron Trading Co Ltd: An investor updated")


def hit(name, cik, form, date, accession, sics=("7370",)):
    return {
        "_id": f"{accession}:doc.htm",
        "_source": {
            "display_names": [f"{name}  (CIK {cik:010d})"],
            "ciks": [f"{cik:010d}"],
            "form": form,
            "file_date": date,
            "biz_locations": ["San Francisco, CA"],
            "sics": list(sics),
        },
    }


def test_ipo_filings_leave_out_companies_that_were_public_already(web, make_ctx):
    import json

    search = "https://efts.sec.gov/LATEST/search-index?forms={}&dateRange=custom"
    period = "&startdt=2024-02-01&enddt=2024-02-29"
    hits = [
        hit("Reddit, Inc.  (RDDT)", 1713445, "S-1", "2024-02-22", "0001-24-1"),
        hit("Reddit, Inc.  (RDDT)", 1713445, "S-1/A", "2024-03-11", "0001-24-2"),
        hit("Ocean Power Technologies, Inc.  (OPTT)", 1378140, "S-1", "2024-02-20", "0002-24-1"),
        hit("American General Life Insurance Co", 5000, "S-1", "2024-02-21", "0003-24-1", ["6311"]),
    ]
    web.add(
        search.format("S-1") + period,
        json.dumps({"hits": {"hits": hits}}),
        content_type="application/json",
    )
    web.add(
        search.format("F-1") + period,
        json.dumps({"hits": {"hits": []}}),
        content_type="application/json",
    )
    subs = "https://data.sec.gov/submissions/CIK{:010d}.json"
    web.add(
        subs.format(1713445),
        json.dumps(
            {
                "filings": {
                    "recent": {"form": ["S-1", "D"], "filingDate": ["2024-02-22", "2021-08-01"]}
                }
            }
        ),
        content_type="application/json",
    )
    web.add(
        subs.format(1378140),
        json.dumps({"filings": {"recent": {"form": ["10-K"], "filingDate": ["2023-07-20"]}}}),
        content_type="application/json",
    )
    source = Sec(
        resource="ipo-filings", contact="me@example.com", since="2024-02-01", until="2024-02-29"
    )
    events = run_source(source, make_ctx())
    assert [e.data["title"] for e in events] == ["Reddit, Inc. filed to go public (S-1)"]
    assert events[0].data["link"].endswith("/1713445/0001241/0001-24-1-index.htm")
    assert events[0].timestamp == "2024-02-22T00:00:00Z"


def test_a_past_period_of_company_events_comes_from_full_text_search(web, make_ctx):
    import json

    from unlimitedpipe.sources.sec import EVENTS

    base = "https://efts.sec.gov/LATEST/search-index?q=%22Item+{}%22&forms=8-K&dateRange=custom"
    period = "&startdt=2024-03-01&enddt=2024-03-03"
    bankrupt = hit("SILVER STAR PROPERTIES REIT, INC", 1402, "8-K", "2024-03-01", "0005-24-1")
    bankrupt["_source"]["items"] = ["1.03", "9.01"]
    mentions = hit("Other Corp  (OTH)", 1403, "8-K", "2024-03-01", "0006-24-1")
    mentions["_source"]["items"] = ["8.01"]  # says "Item 1.03" in its text, files no such item
    for item in EVENTS:
        found = [bankrupt, mentions] if item == "1.03" else []
        web.add(
            base.format(item) + period,
            json.dumps({"hits": {"hits": found}}),
            content_type="application/json",
        )
    source = Sec(
        resource="company-events", contact="me@example.com", since="2024-03-01", until="2024-03-03"
    )
    events = run_source(source, make_ctx())
    assert [e.data["title"] for e in events] == [
        "Silver Star Properties REIT, Inc: bankruptcy or receivership"
    ]
    assert events[0].data["summary"] == (
        "Item 1.03: Bankruptcy or Receivership\nItem 9.01: Financial Statements and Exhibits"
    )


def test_stakes_and_events_read_the_same_from_search_and_from_the_latest_list():
    from unlimitedpipe.sources.sec import listed_events, searched_stake

    stake = hit("ACME CORP  (ACME)", 11, "SC 13D", "2023-05-02", "0007-23-1")
    stake["_source"]["display_names"].append("SMITH JOHN A  (CIK 0000000022)")
    assert searched_stake(stake)["title"] == (
        "Acme Corp: John A Smith disclosed a stake of 5% or more (Schedule 13D)"
    )
    entry = {
        "title": "8-K - DYADIC INTERNATIONAL INC (0001213809) (Filer)",
        "link": f"{FOLDER}/1213809/000121380926000030/0001213809-26-000030-index.htm",
        "summary": "<b>Filed:</b> 2026-09-25 <b>AccNo:</b> 0001213809-26-000030 <b>Size:</b> 1 MB"
        "<br>Item 3.01: Notice of Delisting or Failure to Satisfy a Continued Listing Rule or "
        "Standard; Transfer of Listing<br>Item 9.01: Financial Statements and Exhibits",
        "updated": "2026-09-25T16:05:00-04:00",
    }
    [event] = listed_events([entry, entry])
    assert event["title"] == "Dyadic International Inc: delisting notice or listing transfer"
    assert event["items"] == ["3.01", "9.01"]
