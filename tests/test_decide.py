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
        "Yes: Bitget: $387.0M lost (key compromise) [1]; Duelbits: $7.0M lost (key compromise) [2]."
    )
    assert write("bitcoin price", SOURCES, [3]) == (
        "Bitcoin (BTC) price: $84,292.16 (2026-09-27) [3]. "
        "Bitcoin cost $84,292.1559 at 00:53 UTC [3]."
    )
    assert write("tesla recall?", SOURCES, []) == (
        "The sources do not answer this. The closest is: Bitget: $387.0M lost (key compromise) [1]."
    )
    assert write("แฮกคริปโต", SOURCES, [1, 2]).startswith("มีดังนี้: ")
