import pytest

from unlimitedpipe.sources.usaspending import UsaSpending, award

ROW = {
    "Award ID": "70B03C26F00000123",
    "Recipient Name": "CLARK CONSTRUCTION GROUP LLC",
    "Award Amount": 332000000.0,
    "Awarding Agency": "Department of Homeland Security",
    "Awarding Sub Agency": "U.S. Customs and Border Protection",
    "Description": "THIS TASK ORDER IS FOR A DESIGN BUILD PROJECT IN LAREDO, TX",
    "generated_internal_id": "CONT_AWD_70B03C26F00000123",
    "Base Obligation Date": "2026-09-26",
}


def test_an_award_reads_as_a_sentence_with_its_link():
    found = award(ROW, "contracts")
    assert found["title"] == (
        "Clark Construction Group LLC won a $332M contract from the Department of Homeland Security"
    )
    assert found["summary"].startswith("This task order is for a design build project in laredo")
    assert "Awarded by U.S. Customs and Border Protection" in found["summary"]
    assert found["link"] == "https://www.usaspending.gov/award/CONT_AWD_70B03C26F00000123"
    assert found["published_at"] == "2026-09-26T00:00:00Z"
    grant = award({**ROW, "Recipient Name": "Chicago Transit Authority"}, "grants")
    assert grant["title"].startswith("Chicago Transit Authority was awarded a $332M grant by the")
    assert award({**ROW, "Base Obligation Date": None, "Start Date": None}, "contracts") is None


def test_options_are_checked():
    with pytest.raises(ValueError):
        UsaSpending(resource="contracts", days=400)


def test_recipients_read_the_way_round():
    from unlimitedpipe.sources.usaspending import _recipient

    assert _recipient("HEALTH CARE SERVICES, CALIFORNIA DEPARTMENT OF") == (
        "California Department of Health Care Services"
    )
    assert _recipient("Health &amp; Human SVC Commn TX") == "Health & Human SVC Commn TX"
