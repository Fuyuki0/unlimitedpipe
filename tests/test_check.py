import json
from pathlib import Path

from unlimitedpipe.check import check, markdown


def feed(tmp_path: Path, name: str, outputs: str) -> Path:
    (tmp_path / "feeds").mkdir(exist_ok=True)
    (tmp_path / "public").mkdir(exist_ok=True)
    records = [
        {"title": "M 6.6 near Tadine", "link": "https://q.example/1", "date": "2026-09-25"},
        {"title": "M 5.0 near Ruteng", "link": "https://q.example/2", "date": "2026-09-26"},
    ]
    (tmp_path / "quakes.json").write_text(json.dumps(records))
    path = tmp_path / "feeds" / f"{name}.yml"
    path.write_text(
        f"name: {name}\ndescription: Earthquakes\n"
        "sources: [{type: file, path: ../quakes.json}]\n"
        "operators:\n  - {type: map, assign: ['published_at=date']}\n"
        "  - {type: diff, key: link, only: [added], emit_initial: true}\n"
        f"outputs: {outputs}\n"
    )
    return path


def test_a_good_feed_passes_with_its_items(tmp_path):
    path = feed(tmp_path, "quakes", "[{type: feed, path: ../public/quakes.json}]")
    result = check(path, readme="| quakes | Earthquakes |")
    assert result.ok and result.items == 2 and result.new_on_second_run == 0
    assert result.samples[0]["link"].startswith("https://q.example/")
    assert "✅ `" in markdown([result])


def test_a_feed_without_a_json_feed_or_a_readme_row_is_reported(tmp_path):
    path = feed(tmp_path, "quakes", "[{type: feed, path: ../public/quakes.xml}]")
    result = check(path, readme="nothing listed")
    assert not result.ok
    assert result.problems == ["writes no JSON feed (an output with a .json path)"]
    assert result.warnings == ["is not in the README's list of feeds"]
