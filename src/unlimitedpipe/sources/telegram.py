"""The ``telegram`` source: posts of public Telegram channels, from their public web preview."""

from __future__ import annotations

import re
from typing import Any

from unlimitedpipe.component import Source, arg, opt
from unlimitedpipe.context import Context
from unlimitedpipe.errors import FetchError
from unlimitedpipe.event import Event
from unlimitedpipe.sources._posts import headline

_CHANNEL = re.compile(r"^(?:https?://)?(?:t\.me/(?:s/)?|@)?([A-Za-z][A-Za-z0-9_]{3,31})/?$")


def parse_channel(text: str) -> str:
    match = _CHANNEL.match(text.strip())
    if not match:
        raise ValueError(f"not a Telegram channel: {text!r}; use its name, @name or t.me link")
    return match.group(1)


def _views(text: str | None) -> int | None:
    """``2.97M`` -> 2970000."""
    if not text:
        return None
    match = re.match(r"^([\d.]+)\s*([KMB]?)$", text.strip(), re.IGNORECASE)
    if not match:
        return None
    scale = {"": 1, "K": 1e3, "M": 1e6, "B": 1e9}[match.group(2).upper()]
    return int(float(match.group(1)) * scale)


class Telegram(Source):
    """Recent posts of public Telegram channels, read from the public preview Telegram
    publishes at t.me/s/CHANNEL. Only public channels have one; private chats and groups
    never appear there. No account needed.
    """

    name = "telegram"
    examples = (
        "unlimited telegram durov",
        "unlimited telegram https://t.me/s/telegram | unlimited diff --only added",
    )

    channel: list[str] = arg(
        "Public channel names, @names or t.me links", metavar="CHANNEL...", default_factory=list
    )
    timeout: float = opt("Seconds to wait for each response", default=20.0)

    def __post_init__(self) -> None:
        if not self.channel:
            raise ValueError("telegram needs at least one public channel name")
        self._channels = [parse_channel(c) for c in self.channel]

    async def collect(self, ctx: Context):
        from unlimitedpipe import html

        for channel in self._channels:
            url = f"https://t.me/s/{channel}"
            try:
                response = await ctx.http.get(url, timeout=self.timeout, robots=True)
            except FetchError as exc:
                if (error := ctx.fail(exc, source=self.name, url=url)) is not None:
                    yield error
                continue
            soup = html.parse(response.content, response.encoding)
            messages = soup.select(".tgme_widget_message[data-post]")
            if not messages:
                exc = FetchError(
                    f"{url} shows no posts",
                    url=url,
                    hint="only public channels have a web preview; check the name",
                )
                if (error := ctx.fail(exc, source=self.name, url=url)) is not None:
                    yield error
                continue
            title_node = soup.select_one(".tgme_channel_info_header_title")
            channel_title = title_node.get_text(strip=True) if title_node else channel
            for message in reversed(messages):  # newest first, like the other sources
                yield self._event(url, channel, channel_title, message)

    def _event(self, url: str, channel: str, channel_title: str, message: Any) -> Event:
        post = str(message.get("data-post"))
        body = message.select_one(".tgme_widget_message_text")
        text = ""
        if body:
            for br in body.find_all("br"):
                br.replace_with("\n")  # only real line breaks; links and bold stay inline
            text = "\n".join(" ".join(line.split()) for line in body.get_text().splitlines())
            text = re.sub(r"\n{3,}", "\n\n", text).strip()
        when = message.select_one(".tgme_widget_message_date time")
        views = message.select_one(".tgme_widget_message_views")
        links = [
            a["href"]
            for a in (body.select("a[href]") if body else [])
            if str(a["href"]).startswith("http")
        ]
        link = f"https://t.me/{post}"
        return Event(
            source=self.name,
            type="post",
            key=link,
            source_url=url,
            timestamp=when.get("datetime") if when else None,
            data={
                "title": headline(text) or f"{channel_title}: post {post.rsplit('/', 1)[-1]}",
                "text": text,
                "author": channel,
                "author_name": channel_title,
                "url": link,
                "created_at": when.get("datetime") if when else None,
                "views": _views(views.get_text() if views else None),
                "tags": sorted(set(re.findall(r"#\w+", text))),
                "links": links,
            },
            metadata={"method": "telegram-web-preview"},
        )
