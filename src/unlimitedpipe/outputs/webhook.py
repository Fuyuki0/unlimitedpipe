"""Send events to a webhook: Discord, Slack, or any URL that accepts JSON."""

from __future__ import annotations

import re
from typing import Any, Literal

from unlimitedpipe.component import Output, arg, opt
from unlimitedpipe.errors import FetchError
from unlimitedpipe.event import Event
from unlimitedpipe.outputs.feed import feed_item

DISCORD_LIMIT = 2000
SLACK_LIMIT = 3000
CHAT_SUMMARY = 280  # a chat message is a notification, not the article


def detect_format(url: str) -> str:
    if re.match(r"https://(?:\w+\.)?discord(?:app)?\.com/api/webhooks/", url):
        return "discord"
    if url.startswith("https://hooks.slack.com/"):
        return "slack"
    return "json"


def _discord_escape(text: str) -> str:
    text = re.sub(r"([\\*_~`|>])", r"\\\1", text)
    # A line starting with "#", "-" or "1." would become a heading or a list.
    return re.sub(r"^(\s*)([#-]|\d+\.)", r"\1\\\2", text, flags=re.MULTILINE)


def _short(text: str | None) -> str | None:
    if text is None or len(text) <= CHAT_SUMMARY:
        return text
    return text[:CHAT_SUMMARY].rsplit(" ", 1)[0].rstrip(" ,.;:") + "…"


def _slack_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def discord_message(event: Event) -> dict[str, Any]:
    item = feed_item(event)
    lines = [f"**{_discord_escape(item['title'])}**"]
    if item["summary"]:
        lines.append(_discord_escape(_short(item["summary"]) or ""))
    if item["link"]:
        lines.append(item["link"])
    content = "\n".join(lines)
    if len(content) > DISCORD_LIMIT:
        content = content[: DISCORD_LIMIT - 1] + "…"
    # Never ping anyone: content from the web must not trigger @everyone or role mentions.
    return {"content": content, "allowed_mentions": {"parse": []}}


def slack_message(event: Event) -> dict[str, Any]:
    item = feed_item(event)
    title = _slack_escape(item["title"])
    lines = [f"*<{item['link']}|{title}>*" if item["link"] else f"*{title}*"]
    if item["summary"]:
        lines.append(_slack_escape(_short(item["summary"]) or ""))
    text = "\n".join(lines)
    if len(text) > SLACK_LIMIT:
        text = text[: SLACK_LIMIT - 1] + "…"
    return {"text": text, "unfurl_links": False}


class Webhook(Output):
    """Send each event to a webhook: a Discord or Slack message, or the event as JSON.

    The format follows the URL (Discord and Slack webhooks are recognized) unless --format is
    given. At most --max-messages are sent per run, then one summary message, so a first run
    over a busy feed does not flood a channel. Keep webhook URLs secret: pass them through an
    environment variable (`${DISCORD_WEBHOOK}` in pipeline files). They never appear in
    messages or logs.
    """

    name = "webhook"
    examples = (
        'unlimited web https://shop.example/p | unlimited diff | unlimited webhook "$DISCORD_HOOK"',
        "unlimited run rss https://hnrss.org/frontpage -- grep AI -- webhook https://example.com/hook",
    )

    url: str = arg("Webhook URL", metavar="URL")
    format: Literal["auto", "json", "discord", "slack"] = opt("Message format", default="auto")
    max_messages: int = opt(
        "Messages per run before summarizing the rest (0: no limit)", default=20
    )
    timeout: float = opt("Seconds to wait for each request", default=20.0)

    def __post_init__(self) -> None:
        if not self.url.startswith(("https://", "http://")):
            raise ValueError(
                "the webhook URL must start with https:// (or http:// for local testing)"
            )
        if self.max_messages < 0:
            raise ValueError("--max-messages must be 0 or more")
        self._format = self.format if self.format != "auto" else detect_format(self.url)

    async def open(self, ctx) -> None:
        self._ctx = ctx
        self._sent = 0
        self._skipped = 0

    def _payload(self, event: Event) -> dict[str, Any]:
        if self._format == "discord":
            return discord_message(event)
        if self._format == "slack":
            return slack_message(event)
        return event.to_dict()

    async def _send(self, payload: dict[str, Any]) -> None:
        try:
            await self._ctx.http.post(self.url, json_body=payload, timeout=self.timeout)
        except FetchError as exc:
            self._ctx.fail(exc, source=self.name)

    async def write(self, event: Event) -> None:
        if self.max_messages and self._sent >= self.max_messages:
            self._skipped += 1
            return
        self._sent += 1
        await self._send(self._payload(event))

    async def close(self) -> None:
        if not self._skipped:
            return
        note = f"…and {self._skipped} more (limit: {self.max_messages} messages per run)"
        if self._format == "discord":
            await self._send({"content": note, "allowed_mentions": {"parse": []}})
        elif self._format == "slack":
            await self._send({"text": note})
        else:
            self._ctx.warn(f"webhook: {self._skipped} event(s) not sent ({note})")
