import asyncio
import json

import httpx
import pytest

from tests.conftest import ev
from unlimitedpipe.config import load_pipeline
from unlimitedpipe.errors import ConfigError
from unlimitedpipe.outputs.webhook import Webhook, detect_format, discord_message, slack_message

DISCORD = "https://discord.com/api/webhooks/123/SECRET-TOKEN"
SLACK = "https://hooks.slack.com/services/T0/B0/SECRET"


def change(label="Pro", old="$49", new="$59"):
    return ev(
        {
            "change": "modified",
            "label": label,
            "summary": f"price: {old} → {new}",
            "fields": [{"path": "price", "old": old, "new": new}],
            "after": {"name": label, "price": new, "url": "https://shop.example/pro"},
        },
        type="change",
    )


def send(web, make_ctx, output, events):
    ctx = make_ctx()

    async def go():
        await output.open(ctx)
        for event in events:
            await output.write(event)
        await output.close()
        await ctx.aclose()

    asyncio.run(go())
    return ctx, [json.loads(r.content) for r in web.requests if r.method == "POST"]


def test_format_detection():
    assert detect_format(DISCORD) == "discord"
    assert detect_format("https://discordapp.com/api/webhooks/1/x") == "discord"
    assert detect_format(SLACK) == "slack"
    assert detect_format("https://example.com/hook") == "json"


def test_discord_message_is_safe():
    event = ev({"title": "**Big** @everyone news_", "link": "https://n/1", "summary": "x" * 3000})
    message = discord_message(event)
    assert message["allowed_mentions"] == {"parse": []}
    assert message["content"].startswith("**\\*\\*Big\\*\\* @everyone news\\_**")
    assert len(message["content"]) <= 2000


def test_discord_line_markers_do_not_become_headings():
    message = discord_message(ev({"title": "T", "summary": "# Big claim\n- item\n1. first"}))
    assert message["content"] == "**T**\n\\# Big claim\n\\- item\n\\1. first"


def test_slack_message_links_the_title_and_escapes():
    message = slack_message(ev({"title": "A <b> & c", "link": "https://n/1"}))
    assert message["text"] == "*<https://n/1|A &lt;b&gt; &amp; c>*"
    assert message["unfurl_links"] is False


def test_discord_change_message(web, make_ctx):
    web.add(DISCORD, "", status=204)
    _, payloads = send(web, make_ctx, Webhook(url=DISCORD), [change()])
    assert payloads[0]["content"] == "**Pro: price: $49 → $59**\nhttps://shop.example/pro"


def test_json_webhook_gets_whole_events(web, make_ctx):
    web.add("https://example.com/hook", "{}", content_type="application/json")
    event = change()
    _, payloads = send(web, make_ctx, Webhook(url="https://example.com/hook"), [event])
    assert payloads[0]["schema"] == "unlimitedpipe.event/1"
    assert payloads[0]["id"] == event.id


def test_message_limit_sends_one_summary(web, make_ctx):
    web.add(SLACK, "ok", content_type="text/plain")
    events = [change(label=f"Plan {i}") for i in range(5)]
    _, payloads = send(web, make_ctx, Webhook(url=SLACK, max_messages=2), events)
    assert len(payloads) == 3
    assert payloads[-1]["text"] == "…and 3 more (limit: 2 messages per run)"


def test_discord_rate_limit_is_retried(web, make_ctx):
    calls = []

    def limited(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, json={"retry_after": 0.01, "message": "rate limited"})
        return httpx.Response(204)

    web.pages[DISCORD] = limited
    ctx, _ = send(web, make_ctx, Webhook(url=DISCORD), [change()])
    assert len(calls) == 2 and ctx.failures == 0


def test_failures_never_show_the_secret(web, make_ctx, capsys):
    web.add(DISCORD, '{"message": "Unknown Webhook"}', status=404, content_type="application/json")
    ctx, _ = send(web, make_ctx, Webhook(url=DISCORD), [change()])
    assert ctx.failures == 1
    err = capsys.readouterr().err
    assert "https://discord.com/…" in err and "Unknown Webhook" in err
    assert "SECRET-TOKEN" not in err and "123" not in err


def test_invalid_options():
    with pytest.raises(ValueError, match="https://"):
        Webhook(url="discord.com/api/webhooks/1/x")


def test_pipeline_env_references(tmp_path, monkeypatch):
    path = tmp_path / "p.yml"
    path.write_text(
        "sources: [{type: file, path: d.json}]\noutputs:\n  - type: webhook\n    url: ${HOOK_URL}\n"
    )
    monkeypatch.setenv("HOOK_URL", SLACK)
    assert load_pipeline(path).outputs[0].url == SLACK
    monkeypatch.delenv("HOOK_URL")
    with pytest.raises(ConfigError, match="HOOK_URL is not set") as info:
        load_pipeline(path)
    assert "p.yml:4" in info.value.message
