import asyncio
import sqlite3

import pytest

from tests.conftest import ev
from unlimitedpipe import Context
from unlimitedpipe.outputs.sqlite import Sqlite


def store(path, events, **options):
    output = Sqlite(path=str(path), **options)

    async def go():
        await output.open(Context(quiet=True))
        for event in events:
            await output.write(event)
        await output.close()

    asyncio.run(go())


def test_events_become_queryable_rows(tmp_path):
    db = tmp_path / "sub" / "news.db"
    events = [
        ev({"title": "A", "price": 5}, key="a", source_url="https://s/a"),
        ev({"title": "B", "price": 50}, key="b", type="product"),
    ]
    store(db, events)
    rows = (
        sqlite3.connect(db)
        .execute(
            "SELECT key, type, json_extract(data, '$.title'), json_extract(data, '$.price') "
            "FROM events ORDER BY key"
        )
        .fetchall()
    )
    assert rows == [("a", "record", "A", 5), ("b", "product", "B", 50)]


def test_rerun_stores_only_new_observations(tmp_path):
    db = tmp_path / "news.db"
    store(db, [ev({"title": "A"}, key="a")])
    store(db, [ev({"title": "A"}, key="a"), ev({"title": "A2"}, key="a")])
    count = sqlite3.connect(db).execute("SELECT count(*) FROM events").fetchone()[0]
    assert count == 2


def test_custom_table_and_validation(tmp_path):
    db = tmp_path / "x.db"
    store(db, [ev({"n": 1})], table="prices")
    assert sqlite3.connect(db).execute("SELECT count(*) FROM prices").fetchone()[0] == 1
    with pytest.raises(ValueError, match="plain name"):
        Sqlite(path=str(db), table="x; DROP TABLE events")
