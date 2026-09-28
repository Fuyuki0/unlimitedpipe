import pytest

from unlimitedpipe.names import clean_link, clean_title, readable_name


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("HERTZ GLOBAL HOLDINGS, INC", "Hertz Global Holdings, Inc"),
        ("BNSF RAILWAY COMPANY", "BNSF Railway Company"),
        ("AT&T INC.", "AT&T Inc."),
        ("ASSOCIATION OF AMERICAN RAILROADS", "Association of American Railroads"),
        ("BANK OF AMERICA CORP /DE/", "Bank of America Corp"),
        ("SILVER STAR PROPERTIES REIT, INC", "Silver Star Properties REIT, Inc"),
        ("JEWETT CAMERON TRADING CO LTD", "Jewett Cameron Trading Co Ltd"),
        ("COCA-COLA CO", "Coca-Cola Co"),
        ("Reddit, Inc.", "Reddit, Inc."),  # written by people already
    ],
)
def test_names_in_capitals_are_written_as_people_write_them(raw, expected):
    assert readable_name(raw) == expected


def test_titles_lose_markup_and_links_lose_tracking():
    assert (
        clean_title("Can &#8216;eSUV&#8217;  e-bikes\n go <i>far</i>?")
        == "Can ‘eSUV’ e-bikes go far?"
    )
    assert clean_title("A < b > & c") == "A < b > & c"  # not tags
    assert clean_link("https://x.eu/a/?utm_source=RSS&id=5") == "https://x.eu/a/?id=5"
    assert clean_link("https://x.eu/a/?utm_medium=RSS") == "https://x.eu/a/"
