import asyncio
import http.server
import threading
from pathlib import Path

import pytest

from tests.conftest import run_source
from unlimitedpipe import Context
from unlimitedpipe.http import Response
from unlimitedpipe.sources.web import Web

PAGE = """<html><head><title>Rates</title></head><body><div id="news"></div>
<script>document.getElementById("news").innerHTML =
  '<h2>Policy rate held at 1.50%</h2><a href="/news/1">Read</a>';</script></body></html>"""


class FakeBrowser:
    def __init__(self):
        self.calls = []

    async def render(self, url, *, user_agent, robots, timeout, screenshot):
        self.calls.append((url, robots, screenshot))
        html = b"<html><title>Rates</title><body><h2>Policy rate held at 1.50%</h2></body></html>"
        response = Response(url, url, 200, {"content-type": "text/html"}, html, "utf-8", 5)
        return response, (screenshot / "shot.png" if screenshot else None)

    async def aclose(self):
        pass


def test_web_reads_rendered_pages_through_the_browser(tmp_path, make_ctx):
    browser = FakeBrowser()
    ctx = make_ctx(browser=browser)
    shots = tmp_path / "shots"
    [event] = run_source(
        Web(url=["https://bank.example/news"], browser=True, screenshot=str(shots)), ctx
    )
    assert event.data["headings"][0]["text"] == "Policy rate held at 1.50%"
    assert event.metadata["rendered"] is True
    assert event.metadata["screenshot"] == str(shots / "shot.png")
    assert browser.calls == [("https://bank.example/news", True, shots)]


def test_screenshots_need_the_browser():
    with pytest.raises(ValueError, match="--screenshot needs --browser"):
        Web(url=["https://x.example"], screenshot="shots")


class _Site(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/robots.txt":
            body, status = b"User-agent: *\nDisallow: /private\n", 200
        else:
            body, status = PAGE.encode(), 200
        self.send_response(status)
        self.send_header(
            "content-type", "text/plain" if self.path == "/robots.txt" else "text/html"
        )
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def site():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Site)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def chromium_or_skip():
    pytest.importorskip("playwright.async_api")

    async def launch():
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            await browser.close()

    try:
        asyncio.run(launch())
    except Exception as exc:
        pytest.skip(f"no headless Chromium here: {str(exc).splitlines()[0]}")


def test_a_real_browser_runs_the_page_scripts_and_respects_robots(site, tmp_path):
    chromium_or_skip()
    ctx = Context(quiet=True, state_dir=tmp_path / "s", cache_dir=tmp_path / "c", host_interval=0)
    [event] = run_source(Web(url=[site + "/news"], browser=True, screenshot=str(tmp_path)), ctx)
    assert event.data["headings"][0]["text"] == "Policy rate held at 1.50%"
    assert Path(event.metadata["screenshot"]).stat().st_size > 1000

    ctx = Context(
        quiet=True,
        state_dir=tmp_path / "s",
        cache_dir=tmp_path / "c",
        host_interval=0,
        errors_as_events=True,
    )
    [error] = run_source(Web(url=[site + "/private/page"], browser=True), ctx)
    assert error.type == "error" and "robots.txt" in error.data["error"]


def test_publish_installs_chromium_only_for_pipelines_that_render(tmp_path):
    import subprocess

    from unlimitedpipe.config import load_pipeline
    from unlimitedpipe.publish import plan, workflow

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "feeds").mkdir()
    plain, rendered = tmp_path / "feeds" / "plain.yml", tmp_path / "feeds" / "rendered.yml"
    for path, extra in [(plain, ""), (rendered, ", browser: true")]:
        path.write_text(
            f"name: {path.stem}\nsources: [{{type: web, url: https://x.example{extra}}}]\n"
            f"outputs: [{{type: feed, path: ../public/{path.stem}.xml}}]\n"
        )
    assert "playwright install" not in workflow(plan([(plain, load_pipeline(plain))], 3600))
    both = plan([(p, load_pipeline(p)) for p in (plain, rendered)], 3600)
    assert "python -m playwright install --with-deps chromium" in workflow(both)
