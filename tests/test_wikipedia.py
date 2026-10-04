from datetime import date

from unlimitedpipe.sources.wikipedia import day_page, event_item, events, month_page

PAGE = """<html><body>
<div class="current-events-main vevent" id="2024_January_5">
 <div class="current-events-content description">
  <p><b>Armed conflicts and Attacks</b></p>
  <ul><li><a href="/wiki/Korean_conflict">Korean conflict</a>
   <ul><li><a href="/wiki/North_Korea">North Korea</a> fires 200 artillery shells near
    <a href="/wiki/South_Korea">South Korea</a>'s Yeonpyeong Island, prompting
    "<a href="/wiki/Evacuation">evacuations</a>".
    <a class="external text" href="https://www.cnbc.com/x">(CNBC)</a></li></ul></li></ul>
  <p><b>Sports</b></p>
  <ul><li>Short.</li>
   <li>A team wins the cup after extra time in the final.<sup class="reference">[1]</sup></li></ul>
 </div>
</div>
<div class="current-events-main vevent" id="2024_January_6">
 <div class="current-events-content description">
  <ul><li>Something else happens somewhere in the world today.</li></ul>
 </div>
</div>
</body></html>"""


def test_events_read_topic_section_and_sources():
    found = events(PAGE)
    assert [e["day"] for e in found] == [date(2024, 1, 5)] * 2 + [date(2024, 1, 6)]
    first = found[0]
    assert first["category"] == "Armed conflicts and attacks"
    assert first["topic"] == ["Korean conflict"]
    assert first["text"] == (
        "North Korea fires 200 artillery shells near South Korea's Yeonpyeong Island, "
        'prompting "evacuations".'
    )
    assert first["sources"] == [("CNBC", "https://www.cnbc.com/x")]
    assert found[1]["text"] == "A team wins the cup after extra time in the final."  # no "[1]"
    item = event_item(first)
    assert item["link"] == day_page(date(2024, 1, 5))
    assert item["published_at"] == "2024-01-05T00:00:00Z"
    assert "Topic: Korean conflict." in item["summary"]
    assert "Sources: CNBC." in item["summary"]
    assert "CC BY-SA 4.0" in item["summary"]


def test_events_of_some_days_only():
    assert [e["day"] for e in events(PAGE, {date(2024, 1, 6)})] == [date(2024, 1, 6)]


def test_pages():
    assert day_page(date(2024, 1, 5)).endswith("Portal:Current_events/2024_January_5")
    assert month_page(2024, 1).endswith("Portal:Current_events/January_2024")
