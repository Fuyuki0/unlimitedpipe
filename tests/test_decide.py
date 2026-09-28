from unlimitedpipe.decide import parse, write

SOURCES = [
    {"title": "Bitget: $387.0M lost (key compromise)", "date": "2026-09-24T00:00:00Z"},
    {"title": "Duelbits: $7.0M lost (key compromise)", "date": "2026-09-24T00:00:00Z"},
    {
        "title": "Bitcoin (BTC) price: $84,292.16",
        "summary": "Bitcoin cost $84,292.1559 at 00:53 UTC. From DefiLlama.",
        "date": "2026-09-27T00:53:00Z",
    },
]


def test_a_decision_is_a_few_numbers_or_none():
    assert parse("USE 2 1", 3) == [2, 1]
    assert parse("use 3 3 9 1", 3) == [3, 1]  # each once, only sources that exist
    assert parse("NONE", 3) == []
    assert parse("The sources say...", 3) is None  # not a decision


def test_the_answer_is_written_from_the_picked_sources_only():
    assert write("any crypto hacks?", SOURCES, [1, 2]) == (
        "Found: Bitget: $387.0M lost (key compromise) [1]; "
        "Duelbits: $7.0M lost (key compromise) [2]."
    )
    assert write("bitcoin price", SOURCES, [3]) == (
        "Bitcoin (BTC) price: $84,292.16 (2026-09-27) [3]. "
        "Bitcoin cost $84,292.1559 at 00:53 UTC [3]."
    )
    assert write("tesla recall?", SOURCES, []) == (
        "The sources do not answer this. The closest is: Bitget: $387.0M lost (key compromise) [1]."
    )
    assert write("แฮกคริปโต", SOURCES, [1, 2]).startswith("มีดังนี้: ")


def test_an_answer_about_a_named_period_says_so():
    sources = [{"title": "CVE-2023-4966: Citrix Bleed"}, {"title": "CVE-2023-3519: Citrix"}]
    answer = write("which citrix flaws were exploited in 2023?", sources, [1, 2])
    assert answer == "From 2023: CVE-2023-4966: Citrix Bleed [1]; CVE-2023-3519: Citrix [2]."


def test_abbreviations_do_not_end_a_sentence_and_dates_are_not_repeated():
    from unlimitedpipe.decide import first_sentence

    text = "Inflation from FRED (Federal Reserve Bank of St. Louis). Data, not advice."
    assert first_sentence(text) == "Inflation from FRED (Federal Reserve Bank of St. Louis)"
    source = {"title": "US inflation: 8.98% (2022-06)", "date": "2022-06-01", "summary": ""}
    assert write("us inflation june 2022", [source], [1]) == "US inflation: 8.98% (2022-06) [1]."
