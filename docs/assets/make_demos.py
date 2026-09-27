"""Record the README's terminal pictures from real runs, as SVG.

    .venv/bin/python docs/assets/make_demos.py

Runs `search` and `ask` against the live catalog, in process, through the same readable output
the terminal shows, and saves what they printed. `ask` uses the public ask model through Ollama
(`ollama pull hf.co/unlimitedpipe/ask-0.5b-GGUF`).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from rich.console import Console

from unlimitedpipe.context import Context
from unlimitedpipe.outputs.pretty import Pretty
from unlimitedpipe.sources.ask import Ask
from unlimitedpipe.sources.search import Search

HERE = Path(__file__).parent
MODEL = "hf.co/unlimitedpipe/ask-0.5b-GGUF:latest"


async def record(command: str, source, path: Path, width: int = 110) -> None:
    import io

    console = Console(
        record=True, width=width, highlight=False, force_terminal=True, file=io.StringIO()
    )
    console.print(f"$ {command}", style="bold")
    output = Pretty()
    await output.open(None)
    output._console = console
    ctx = Context(quiet=True)
    try:
        async for event in source.collect(ctx):
            await output.write(event)
    finally:
        await ctx.aclose()
    console.save_svg(str(path), title=command.split(" --")[0])
    print(f"wrote {path}")


async def main() -> None:
    await record(
        'unlimited ask "any big crypto hacks this week?"',
        Ask(question=["any big crypto hacks this week?"], model=MODEL, sources=3),
        HERE / "ask.svg",
    )
    await record(
        "unlimited search flood bangkok --limit 3",
        Search(words=["flood", "bangkok"], limit=3),
        HERE / "search.svg",
    )


if __name__ == "__main__":
    asyncio.run(main())
