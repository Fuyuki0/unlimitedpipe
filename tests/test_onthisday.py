import json

from unlimitedpipe import onthisday
from unlimitedpipe.archive import append


def test_each_date_gets_its_biggest_past_events(tmp_path):
    items = [
        {"feed": "earthquakes", "title": "M 9.1 - 2011 Great Tohoku Earthquake, Japan",
         "link": "https://e/1", "date": "2011-03-11T05:46:00Z"},
        {"feed": "earthquakes", "title": "M 5.1 - small one", "link": "https://e/2",
         "date": "2012-03-11T00:00:00Z"},
        {"feed": "world-events", "title": "Bombs on Madrid trains kill at least 190 people.",
         "link": "https://w/1", "date": "2004-03-11T00:00:00Z"},
        {"feed": "world-events", "title": "More than 12,000 dead pigs are found in the river.",
         "link": "https://w/2", "date": "2013-03-11T00:00:00Z"},
        {"feed": "hurricanes", "title": "Hurricane Katrina (2005) peaked at Category 5",
         "link": "https://h/1", "date": "2005-08-28T18:00:00Z"},
    ]  # fmt: skip
    append(tmp_path, items, "2026-10-04T00:00:00Z")
    assert onthisday.build(tmp_path) == 2
    march = json.loads((tmp_path / "on-this-day" / "03-11.json").read_text())
    assert [i["date"][:4] for i in march["items"]] == ["2011", "2004"]  # newest first, big only
    assert "Katrina" in (tmp_path / "on-this-day" / "08-28.json").read_text()
    page = onthisday.page("Feeds", "")
    assert "on-this-day/${key}.json" in page and "<title>On this day</title>" in page
