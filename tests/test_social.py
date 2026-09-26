import json
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from tests.conftest import run_source
from unlimitedpipe.errors import UsageError
from unlimitedpipe.sources._posts import headline
from unlimitedpipe.sources.mastodon import Mastodon
from unlimitedpipe.sources.reddit import Reddit
from unlimitedpipe.sources.telegram import Telegram, _views, parse_channel
from unlimitedpipe.sources.x import X
from unlimitedpipe.sources.youtube import YouTube

STATUS = {
    "id": "1",
    "url": "https://mastodon.social/@news/1",
    "created_at": "2026-09-26T10:12:00.000Z",
    "content": "<p>Bangkok declares a flood disaster <a href='#'>#flood</a></p>",
    "language": "en",
    "account": {"acct": "news@example.social", "display_name": "News"},
    "tags": [{"name": "flood"}],
    "favourites_count": 5,
    "reblogs_count": 2,
    "replies_count": 1,
    "card": {"url": "https://news.example/flood"},
}


def test_headline_skips_empty_starts_and_stays_short():
    assert headline("🤝\n\nTelegram sponsors Codeforces, the largest contest site") == (
        "🤝 Telegram sponsors Codeforces, the largest contest site"
    )
    assert len(headline("word " * 100)) == 120


def test_mastodon_reads_tags_and_accounts_and_unwraps_boosts(web, make_ctx):
    base = "https://mastodon.social/api/v1"
    web.add(
        f"{base}/timelines/tag/flood?limit=20",
        json.dumps([STATUS]),
        content_type="application/json",
    )
    boost = {"reblog": STATUS, "account": {"acct": "fan"}}
    web.add(
        f"{base}/accounts/lookup?acct=news%40example.social",
        json.dumps({"id": "7"}),
        content_type="application/json",
    )
    web.add(
        f"{base}/accounts/7/statuses?limit=20&exclude_replies=true",
        json.dumps([boost]),
        content_type="application/json",
    )
    events = run_source(Mastodon(target=["#flood", "@news@example.social"]), make_ctx())
    assert [e.data["title"] for e in events] == ["Bangkok declares a flood disaster #flood"] * 2
    first, boosted = events
    assert first.type == "post" and first.key == STATUS["url"]
    assert first.data["tags"] == ["#flood"] and first.data["links"] == [
        "https://news.example/flood"
    ]
    assert first.data["likes"] == 5 and boosted.data["shared_by"] == "fan"
    with pytest.raises(ValueError, match="needs a target"):
        Mastodon()


TELEGRAM = """<html><div class="tgme_channel_info_header_title">Durov's Channel</div>
<div class="tgme_widget_message" data-post="durov/547"><div class="tgme_widget_message_text">
💸 In one month <b>Telegram</b> awarded <a href="https://t.me/contest">$2,222,000</a><br><br>#contest
</div><span class="tgme_widget_message_views">2.55M</span>
<a class="tgme_widget_message_date"><time datetime="2026-09-06T17:40:39+00:00"></time></a></div>
<div class="tgme_widget_message" data-post="durov/548"><div class="tgme_widget_message_text">
Telegram sponsors Codeforces</div></div></html>"""


def test_telegram_reads_public_channel_previews_newest_first(web, make_ctx):
    web.add("https://t.me/s/durov", TELEGRAM)
    events = run_source(Telegram(channel=["https://t.me/durov"]), make_ctx())
    assert [e.key for e in events] == ["https://t.me/durov/548", "https://t.me/durov/547"]
    older = events[1].data
    assert older["title"] == "💸 In one month Telegram awarded $2,222,000"
    assert older["views"] == 2_550_000 and older["tags"] == ["#contest"]
    assert older["links"] == ["https://t.me/contest"] and older["author_name"] == "Durov's Channel"
    assert parse_channel("@durov") == parse_channel("t.me/s/durov") == "durov"
    assert _views("12.5K") == 12500 and _views(None) is None
    with pytest.raises(ValueError, match="not a Telegram channel"):
        parse_channel("x")


def test_telegram_explains_channels_without_a_preview(web, make_ctx):
    web.add("https://t.me/s/privatething", "<html>nothing</html>")
    [error] = run_source(Telegram(channel=["privatething"]), make_ctx(errors_as_events=True))
    assert "only public channels" in error.data["hint"]


def test_youtube_reads_a_channels_uploads_with_a_key(web, make_ctx, monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "k")
    api = "https://www.googleapis.com/youtube/v3"
    web.add(
        f"{api}/channels?part=contentDetails&key=k&forHandle=%40NASA",
        json.dumps({"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UU1"}}}]}),
        content_type="application/json",
    )
    web.add(
        f"{api}/playlistItems?part=snippet&playlistId=UU1&maxResults=10&key=k",
        json.dumps(
            {
                "items": [
                    {
                        "snippet": {
                            "title": "Artemis update",
                            "channelTitle": "NASA",
                            "publishedAt": "2026-09-25T15:00:00Z",
                            "resourceId": {"videoId": "abc"},
                        }
                    }
                ]
            }
        ),
        content_type="application/json",
    )
    [video] = run_source(YouTube(resource="videos", target=["@NASA"]), make_ctx())
    assert video.type == "video" and video.data["url"] == "https://www.youtube.com/watch?v=abc"
    assert video.data["channel"] == "NASA" and video.timestamp == "2026-09-25T15:00:00Z"
    monkeypatch.delenv("YOUTUBE_API_KEY")
    with pytest.raises(UsageError, match="YouTube Data API key"):
        run_source(YouTube(resource="videos", target=["@NASA"]), make_ctx())


def test_reddit_signs_in_as_your_app_and_reads_listings(web, make_ctx, monkeypatch):
    monkeypatch.setenv("REDDIT_CLIENT_ID", "id")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "secret")
    monkeypatch.setenv("REDDIT_USERNAME", "ana")

    def token(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"].startswith("Basic ")
        assert parse_qs(request.content.decode()) == {"grant_type": ["client_credentials"]}
        return httpx.Response(200, json={"access_token": "t"})

    def listing(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "bearer t"
        assert request.headers["user-agent"].endswith("(by /u/ana)")
        post = {
            "title": "Flooding in Bang Na",
            "permalink": "/r/Thailand/comments/x/flooding/",
            "author": "somchai",
            "created_utc": 1790400000,
            "score": 42,
            "num_comments": 7,
            "is_self": True,
            "selftext": "Water is knee deep",
            "subreddit_name_prefixed": "r/Thailand",
        }
        return httpx.Response(200, json={"data": {"children": [{"data": post}]}})

    web.pages["https://www.reddit.com/api/v1/access_token"] = token
    web.pages["https://oauth.reddit.com/r/Thailand/new?limit=25&raw_json=1"] = listing
    [post] = run_source(Reddit(subreddit=["r/Thailand"]), make_ctx())
    assert post.data["title"] == "Flooding in Bang Na" and post.data["score"] == 42
    assert post.key == "https://www.reddit.com/r/Thailand/comments/x/flooding/"
    assert post.timestamp == "2026-09-26T05:20:00Z"
    monkeypatch.delenv("REDDIT_CLIENT_ID")
    with pytest.raises(UsageError, match="your own free Reddit app"):
        run_source(Reddit(subreddit=["Thailand"]), make_ctx())


def test_x_reads_through_the_official_api_with_your_token(web, make_ctx, monkeypatch):
    monkeypatch.setenv("X_BEARER_TOKEN", "tok")

    def search(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer tok"
        assert parse_qs(urlsplit(str(request.url)).query)["query"] == ["bitcoin etf"]
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "9",
                        "text": "Bitcoin ETF inflows hit a record #BTC",
                        "author_id": "u1",
                        "created_at": "2026-09-26T08:00:00.000Z",
                        "public_metrics": {"like_count": 10, "retweet_count": 3},
                        "entities": {"hashtags": [{"tag": "BTC"}]},
                    }
                ],
                "includes": {"users": [{"id": "u1", "username": "markets", "name": "Markets"}]},
            },
        )

    url = "https://api.x.com/2/tweets/search/recent"
    web.pages[
        url
        + "?"
        + "&".join(
            [
                "tweet.fields=created_at%2Cpublic_metrics%2Clang%2Centities%2Cauthor_id",
                "expansions=author_id",
                "user.fields=username%2Cname",
                "max_results=10",
                "query=bitcoin+etf",
            ]
        )
    ] = search
    [post] = run_source(X(resource="search", target=["bitcoin", "etf"]), make_ctx())
    assert post.data["url"] == "https://x.com/markets/status/9"
    assert post.data["author"] == "@markets" and post.data["tags"] == ["#BTC"]
    assert post.data["likes"] == 10


def test_x_explains_that_reading_needs_a_plan(web, make_ctx, monkeypatch):
    monkeypatch.delenv("X_BEARER_TOKEN", raising=False)
    with pytest.raises(UsageError, match="bearer token"):
        run_source(X(resource="search", target=["bitcoin"]), make_ctx())
    monkeypatch.setenv("X_BEARER_TOKEN", "tok")
    web.pages["https://api.x.com/2/users/by/username/nasa"] = lambda r: httpx.Response(
        403, json={"title": "Client Forbidden"}
    )
    [error] = run_source(X(resource="posts", target=["@nasa"]), make_ctx(errors_as_events=True))
    assert "403" in error.data["error"] and "plan that includes reads" in error.data["hint"]
