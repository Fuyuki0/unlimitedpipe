import asyncio
import json
import subprocess
import sys

import httpx
import pytest

from unlimitedpipe import Context
from unlimitedpipe.errors import FetchError
from unlimitedpipe.http import HttpClient
from unlimitedpipe.mcp import Server, builtin_tools, pipeline_tools


def call(server, method, params=None, request_id=1):
    message = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}
    return asyncio.run(server.handle(message))


@pytest.fixture
def server(web, tmp_path):
    web.add("https://acme.example/", "<title>Acme</title><h1>Hello</h1>")

    def context(**options):
        return Context(
            transport=httpx.MockTransport(web.handler),
            state_dir=tmp_path / "state",
            cache_dir=tmp_path / "cache",
            host_interval=0,
            **options,
        )

    return Server(builtin_tools(), context=context)


def test_initialize_negotiates_the_protocol(server):
    result = call(server, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})[
        "result"
    ]
    assert result["protocolVersion"] == "2025-06-18"
    assert result["capabilities"] == {"tools": {"listChanged": False}}
    assert result["serverInfo"]["name"] == "unlimitedpipe"
    unknown = call(server, "initialize", {"protocolVersion": "1999-01-01"})["result"]
    assert unknown["protocolVersion"] == "2025-11-25"


def test_tools_list_and_errors(server):
    tools = call(server, "tools/list")["result"]["tools"]
    assert [t["name"] for t in tools] == ["fetch_page", "read_feed", "inspect_url", "github"]
    assert all(t["inputSchema"]["type"] == "object" for t in tools)
    assert call(server, "nope")["error"]["code"] == -32601
    assert call(server, "tools/call", {"name": "nope"})["error"]["code"] == -32602
    assert (
        asyncio.run(server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        is None
    )
    assert call(server, "ping")["result"] == {}


def test_fetch_page_returns_events_with_provenance(server):
    call(server, "initialize", {"protocolVersion": "2025-06-18"})
    result = call(
        server, "tools/call", {"name": "fetch_page", "arguments": {"url": "https://acme.example/"}}
    )["result"]
    assert result["isError"] is False
    [event] = result["structuredContent"]["events"]
    assert event["data"]["title"] == "Acme"
    assert event["source_url"] == "https://acme.example/"
    assert event["via"] == ["web", "limit"]
    assert json.loads(result["content"][0]["text"]) == result["structuredContent"]


def test_tool_errors_are_results_not_protocol_errors(server):
    result = call(server, "tools/call", {"name": "fetch_page", "arguments": {}})["result"]
    assert result["isError"] is True and "missing argument: url" in result["content"][0]["text"]
    result = call(
        server,
        "tools/call",
        {"name": "fetch_page", "arguments": {"url": "https://acme.example/nope"}},
    )["result"]
    assert result["isError"] is True and "404" in result["content"][0]["text"]


def test_private_addresses_are_refused_even_after_redirects(tmp_path):
    def handler(request):
        if request.url.host == "public.example":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/admin"})
        return httpx.Response(200, text="internal")

    async def fetch(url):
        http = HttpClient(
            cache_dir=tmp_path, transport=httpx.MockTransport(handler), interval=0, public_only=True
        )
        try:
            return await http.get(url, retries=0)
        finally:
            await http.aclose()

    with pytest.raises(FetchError, match="private address"):
        asyncio.run(fetch("http://127.0.0.1/"))
    with pytest.raises(FetchError, match=r"127\.0\.0\.1 resolves to a private address"):
        asyncio.run(fetch("http://public.example/"))


def test_pipelines_become_tools(tmp_path):
    (tmp_path / "d.json").write_text('[{"name": "Pro", "price": 49}]')
    pipeline = tmp_path / "plans.yml"
    pipeline.write_text(
        "name: plan-watch\n"
        "sources: [{type: file, path: d.json}]\n"
        "operators: [{type: diff, key: name}]\n"
    )
    [tool] = pipeline_tools([pipeline])
    assert tool.name == "plan_watch" and "changed since its previous run" in tool.description
    assert tool.public_only is False
    server = Server([tool], context=lambda **o: Context(state_dir=tmp_path / "state", **o))
    first = call(server, "tools/call", {"name": "plan_watch"})["result"]
    assert json.loads(first["content"][0]["text"]) == {"events": []}  # baseline
    (tmp_path / "d.json").write_text('[{"name": "Pro", "price": 59}]')
    second = json.loads(
        call(server, "tools/call", {"name": "plan_watch"})["result"]["content"][0]["text"]
    )
    assert second["events"][0]["data"]["summary"] == "price: 49 → 59"


def test_stdio_server_end_to_end(tmp_path):
    (tmp_path / "d.json").write_text('[{"name": "Pro"}]')
    pipeline = tmp_path / "p.yml"
    pipeline.write_text("name: p\nsources: [{type: file, path: d.json}]\n")
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18"},
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "p"}},
    ]
    stdin = "".join(json.dumps(m) + "\n" for m in messages) + "not json\n"
    result = subprocess.run(
        [sys.executable, "-m", "unlimitedpipe", "mcp", "--no-builtin", str(pipeline)],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=60,
    )
    responses = [json.loads(line) for line in result.stdout.splitlines()]
    assert [r.get("id") for r in responses] == [1, 2, None]
    assert json.loads(responses[1]["result"]["content"][0]["text"])["events"][0]["data"] == {
        "name": "Pro"
    }
    assert responses[2]["error"]["code"] == -32700
