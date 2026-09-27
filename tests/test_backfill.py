import json
from datetime import date
from pathlib import Path

import pytest

from unlimitedpipe.backfill import backfill, parse_day, parse_every, windows
from unlimitedpipe.errors import UsageError


def quakes(tmp_path: Path, uses_year: bool = True) -> Path:
    (tmp_path / "feeds").mkdir()
    (tmp_path / "public").mkdir()
    by_year = {
        "2024": [
            {"title": "M 6.1 near Hualien", "link": "https://q.example/1", "date": "2024-04-02"},
            {"title": "M 5.0 near Kobe", "link": "https://q.example/2", "date": "2023-12-30"},
        ],
        "2025": [
            {"title": "M 7.7 near Mandalay", "link": "https://q.example/3", "date": "2025-03-28"},
            {"title": "M 4.9, no date", "link": "https://q.example/4"},
        ],
    }
    for year, records in by_year.items():
        (tmp_path / f"quakes-{year}.json").write_text(json.dumps(records))
    (tmp_path / "quakes-all.json").write_text(json.dumps(by_year["2024"] + by_year["2025"]))
    source = "../quakes-${YEAR}.json" if uses_year else "../quakes-all.json"
    path = tmp_path / "feeds" / "quakes.yml"
    path.write_text(
        "name: quakes\n"
        f"sources: [{{type: file, path: '{source}'}}]\n"
        "operators:\n  - {type: map, assign: ['published_at=date']}\n  - {type: limit, count: 1}\n"
        "  - {type: diff, key: link, only: [added], emit_initial: true}\n"
        "outputs: [{type: feed, path: ../public/quakes.json}]\n"
    )
    return path


def archived(site: Path) -> list[dict]:
    return [
        json.loads(line)
        for path in sorted((site / "archive").glob("*.jsonl"))
        for line in path.read_text().splitlines()
    ]


def test_windows_follow_the_calendar_or_a_number_of_days():
    assert windows(date(2024, 1, 15), date(2024, 3, 10), "month") == [
        (date(2024, 1, 15), date(2024, 1, 31)),
        (date(2024, 2, 1), date(2024, 2, 29)),
        (date(2024, 3, 1), date(2024, 3, 10)),
    ]
    assert windows(date(2024, 11, 1), date(2025, 2, 1), "quarter")[1] == (
        date(2025, 1, 1),
        date(2025, 2, 1),
    )
    assert windows(date(2024, 1, 1), date(2024, 1, 20), "10d") == [
        (date(2024, 1, 1), date(2024, 1, 10)),
        (date(2024, 1, 11), date(2024, 1, 20)),
    ]
    assert parse_day("2024-02", end=True) == date(2024, 2, 29)
    assert parse_day("2024") == date(2024, 1, 1)
    with pytest.raises(UsageError):
        parse_every("fortnight")
    with pytest.raises(UsageError):
        parse_day("last year")


def test_backfill_runs_the_feed_once_per_window_into_the_archive(tmp_path):
    path = quakes(tmp_path)
    site = tmp_path / "public"
    result = backfill(path, site, date(2024, 1, 1), date(2025, 12, 31), "year", pause=0)
    items = archived(site)
    # 2023-12-30 is before --from; the undated one would land in the wrong month
    assert sorted(i["title"] for i in items) == ["M 6.1 near Hualien", "M 7.7 near Mandalay"]
    assert result.months == {"2024-04": 1, "2025-03": 1} and result.undated == 1
    assert [w.found for w in result.windows] == [2, 2]
    assert items[0]["feed"] == "quakes" and items[0]["date"].startswith("2024-04-02")
    assert not (site / "quakes.json").exists()  # the feed's own files stay as they are
    again = backfill(path, site, date(2024, 1, 1), date(2025, 12, 31), "year", pause=0)
    assert again.added == 0 and len(archived(site)) == 2


def test_a_feed_without_dates_runs_once_and_keeps_the_items_in_range(tmp_path):
    path = quakes(tmp_path, uses_year=False)
    site = tmp_path / "public"
    result = backfill(
        path, site, date(2025, 1, 1), date(2025, 12, 31), "month", dry_run=True, pause=0
    )
    assert len(result.windows) == 1 and result.windows[0].added == 1
    assert result.samples[0]["title"] == "M 7.7 near Mandalay"
    assert not (site / "archive").exists()  # a dry run writes nothing


def test_backfill_command_reports_what_it_added(tmp_path):
    from click.testing import CliRunner

    from unlimitedpipe.cli import cli

    path = quakes(tmp_path)
    result = CliRunner().invoke(
        cli,
        [
            "backfill",
            str(path),
            "--from",
            "2024",
            "--to",
            "2025",
            "--every",
            "year",
            "--pause",
            "0",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "quakes: added 2 item(s)" in result.output
    assert "1 undated item(s) left out" in result.output
    assert len(archived(tmp_path / "public")) == 2
