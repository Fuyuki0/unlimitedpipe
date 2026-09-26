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
        ("AJB CAPITAL, LLC", "Ajb Capital Llc"),
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
        "NVIDIA CORP (NVDA): Jen Hsun Huang (President and CEO, director) "
        "sold 100,000 shares at $182.00 ($18.2M)"
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


def test_the_sec_needs_a_contact_email(make_ctx, monkeypatch):
    monkeypatch.delenv("SEC_CONTACT", raising=False)
    with pytest.raises(UsageError, match="contact email"):
        run_source(Sec(resource="insider-trades"), make_ctx())
    with pytest.raises(ValueError, match="unknown transaction code"):
        Sec(resource="insider-trades", code=["Z"])
