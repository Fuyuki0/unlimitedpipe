"""Send events to a webhook: Discord, Slack, ntfy (phone notifications), Telegram, or any URL
that accepts JSON."""

from __future__ import annotations

import re
from typing import Any, Literal
from urllib.parse import urlsplit

from unlimitedpipe.component import Output, arg, opt
from unlimitedpipe.errors import FetchError
from unlimitedpipe.event import Event
from unlimitedpipe.outputs.feed import feed_item

DISCORD_LIMIT = 2000
SLACK_LIMIT = 3000
CHAT_SUMMARY = 280  # a chat message is a notification, not the article


TELEGRAM_LIMIT = 4096


def detect_format(url: str) -> str:
    if re.match(r"https://(?:\w+\.)?discord(?:app)?\.com/api/webhooks/", url):
        return "discord"
    if url.startswith("https://hooks.slack.com/"):
        return "slack"
    if re.match(r"https://api\.telegram\.org/bot[^/]+/sendMessage\?", url):
        return "telegram"
    if re.match(r"https?://ntfy\.", url):  # ntfy.sh, or a server of your own at ntfy.example
        return "ntfy"
    return "json"


def expand_target(target: str) -> str:
    """``ntfy:TOPIC`` as its ntfy.sh URL; any URL as it is."""
    if target.startswith("ntfy:") and not target.startswith("ntfy://"):
        return f"https://ntfy.sh/{target.removeprefix('ntfy:')}"
    return target


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


def ntfy_message(event: Event, topic: str) -> dict[str, Any]:
    """A phone notification: the title, the summary, and a tap that opens the source."""
    item = feed_item(event)
    message: dict[str, Any] = {
        "topic": topic,
        "title": item["title"][:250],
        "message": _short(item["summary"]) or item["link"] or item["title"],
    }
    if item["link"]:
        message["click"] = item["link"]
    return message


def telegram_message(event: Event) -> dict[str, Any]:
    item = feed_item(event)
    lines = [item["title"]]
    if item["summary"]:
        lines.append(_short(item["summary"]) or "")
    if item["link"]:
        lines.append(item["link"])
    text = "\n".join(lines)
    if len(text) > TELEGRAM_LIMIT:
        text = text[: TELEGRAM_LIMIT - 1] + "…"
    # plain text: no parse mode, so nothing from the web is read as markup
    return {"text": text, "disable_web_page_preview": True}


class Webhook(Output):
    """Send each event to a webhook: a Discord, Slack or Telegram message, a phone notification
    through ntfy, or the event as JSON.

    The format follows the URL (Discord and Slack webhooks, Telegram's
    `https://api.telegram.org/botTOKEN/sendMessage?chat_id=ID` and ntfy servers are recognized;
    `ntfy:TOPIC` is short for `https://ntfy.sh/TOPIC`) unless --format is given. At most
    --max-messages are sent per run, then one summary message, so a first run over a busy feed
    does not flood a channel. Keep webhook URLs secret: pass them through an
    environment variable (`${DISCORD_WEBHOOK}` in pipeline files). They never appear in
    messages or logs.
    """

    name = "webhook"
    examples = (
        'unlimited web https://shop.example/p | unlimited diff | unlimited webhook "$DISCORD_HOOK"',
        "unlimited run rss https://hnrss.org/frontpage -- grep AI -- webhook https://example.com/hook",
        "unlimited search tsunami | unlimited diff | unlimited webhook ntfy:my-tsunami-alerts",
    )

    url: str = arg("Webhook URL", metavar="URL")
    format: Literal["auto", "json", "discord", "slack", "ntfy", "telegram"] = opt(
        "Message format", default="auto"
    )
    max_messages: int = opt(
        "Messages per run before summarizing the rest (0: no limit)", default=20
    )
    timeout: float = opt("Seconds to wait for each request", default=20.0)
    header: list[str] = opt(
        "A request header, `Name: value` (repeatable), e.g. `Authorization: Bearer ${TOKEN}` for "
        "a server that only lets you post (your own ntfy). Kept out of provenance and outputs",
        default_factory=list,
        metavar="HEADER",
        secret=True,
    )

    def __post_init__(self) -> None:
        self.url = expand_target(self.url)
        self._headers: dict[str, str] = {}
        for line in self.header:
            name, colon, value = line.partition(":")
            if not (colon and name.strip() and value.strip()):
                raise ValueError("--header takes `Name: value`")
            self._headers[name.strip()] = value.strip()
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
        if self._format == "ntfy":
            return ntfy_message(event, self._topic)
        if self._format == "telegram":
            return telegram_message(event)
        return event.to_dict()

    @property
    def _topic(self) -> str:
        return urlsplit(self.url).path.strip("/")

    @property
    def _target(self) -> str:
        if self._format == "ntfy":  # ntfy takes JSON at its root, with the topic inside
            parts = urlsplit(self.url)
            return f"{parts.scheme}://{parts.netloc}/"
        return self.url

    async def _send(self, payload: dict[str, Any]) -> None:
        try:
            await self._ctx.http.post(
                self._target, json_body=payload, headers=self._headers or None, timeout=self.timeout
            )
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
        elif self._format in ("slack", "telegram"):
            await self._send({"text": note})
        elif self._format == "ntfy":
            await self._send({"topic": self._topic, "message": note})
        else:
            self._ctx.warn(f"webhook: {self._skipped} event(s) not sent ({note})")
