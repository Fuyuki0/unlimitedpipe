"""Offline catalogs: download one into a folder, and serve it on this machine or the local
network. `search --catalog DIR` and `ask --catalog DIR` then work without the internet."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any

from unlimitedpipe.context import Context
from unlimitedpipe.errors import FetchError, UsageError
from unlimitedpipe.sources.search import catalog_url, join, load_catalog, read


def _safe(relative: str) -> PurePosixPath:
    """A catalog's own relative path, never one that climbs out of the folder."""
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise FetchError(f"refusing the path {relative!r} from the catalog", url=relative)
    return path


async def mirror(
    ctx: Context, catalog: str | None, folder: Path, *, since: str | None, feeds: bool
) -> dict[str, Any]:
    """Copy a catalog's search data (feeds.json, its archive, its index page) and, with
    ``feeds``, every feed file into ``folder``. Returns what was copied."""
    url = catalog_url(catalog)
    document = await load_catalog(ctx, url)
    folder.mkdir(parents=True, exist_ok=True)
    copied = {"files": 0, "months": 0, "items": len(document.get("items", []))}

    async def copy(relative: str, required: bool = True) -> bytes | None:
        target = folder / _safe(relative)
        try:
            content = await read(ctx, join(url, relative))
        except FetchError:
            if required:
                raise
            return None
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        copied["files"] += 1
        return content

    (folder / "feeds.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    copied["files"] += 1
    await copy("index.html", required=False)
    index_path = document.get("archive") or "archive/index.json"
    index = await copy(index_path, required=False)
    if index:
        for month in json.loads(index).get("months", []):
            if since and str(month.get("month", "")) < since[:7]:
                continue
            archive_dir = str(PurePosixPath(index_path).parent)
            await copy(f"{archive_dir}/{month.get('file')}")
            copied["months"] += 1
    if feeds:
        for feed in document.get("feeds", []):
            for relative in feed.get("files", []):
                await copy(relative, required=False)
    return copied


def serve(folder: Path, *, port: int, lan: bool) -> None:
    """Serve a catalog folder over HTTP until Ctrl+C, read-only."""
    import contextlib
    import functools
    import http.server
    import ipaddress
    import socket

    if not (folder / "feeds.json").is_file():
        raise UsageError(
            f"{folder} has no feeds.json", hint="download a catalog first: unlimited mirror DIR"
        )

    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass

        def end_headers(self) -> None:
            self.send_header("Cache-Control", "no-cache")
            super().end_headers()

    host = "0.0.0.0" if lan else "127.0.0.1"
    handler = functools.partial(Handler, directory=str(folder))
    try:
        server = http.server.ThreadingHTTPServer((host, port), handler)
    except OSError as exc:
        raise UsageError(
            f"cannot listen on port {port}: {exc.strerror or exc}",
            hint="another program uses it; pick another with --port",
        ) from None
    with server:
        import click

        actual = server.server_address[1]
        click.echo(f"Serving {folder} at http://127.0.0.1:{actual}/", err=True)
        if lan:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                    probe.connect(("192.0.2.1", 80))  # picks the LAN interface; sends nothing
                    address = probe.getsockname()[0]
                click.echo(f"On your network: http://{address}:{actual}/", err=True)
                if not ipaddress.ip_address(address).is_private:
                    click.echo(
                        f"warning: {address} is a public address, so anyone on the internet "
                        "can open this. Use a firewall, or leave out --lan.",
                        err=True,
                    )
            except OSError:
                pass
        click.echo("Press Ctrl+C to stop.", err=True)
        with contextlib.suppress(KeyboardInterrupt):
            server.serve_forever()
