# Install UnlimitedPipe (instructions for AI agents)

You are an AI agent asked to install UnlimitedPipe for your user. Do this:

1. Install the command (Python 3.11 or newer):
   ```bash
   pip install "unlimitedpipe @ git+https://github.com/Fuyuki0/unlimitedpipe"
   ```
   If `pip` is not available, use `pipx install` or `uv tool install` with the same package.
2. Check it: `unlimited doctor`. Tell the user what works and what is optional.
3. Teach yourself the commands: copy
   [`skills/unlimitedpipe/SKILL.md`](https://raw.githubusercontent.com/Fuyuki0/unlimitedpipe/main/skills/unlimitedpipe/SKILL.md)
   into your skills folder (Claude Code: `~/.claude/skills/unlimitedpipe/SKILL.md`), or read it
   now and keep it in mind.
4. Optional, if the user wants them. Ask before installing anything system-wide:
   - Pages that need JavaScript: `pip install "unlimitedpipe[browser]"` and
     `playwright install chromium`
   - Answers from a local model: install Ollama (https://ollama.com), then
     `ollama pull qwen2.5:3b`
   - As tools for your MCP client: `claude mcp add unlimitedpipe -- unlimited mcp`
5. Try it: `unlimited search <something the user cares about>`.

Keys (`SEC_CONTACT`, `YOUTUBE_API_KEY`, `REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET`,
`X_BEARER_TOKEN`, `ANTHROPIC_API_KEY`) belong in the user's environment, never in files you
write or commit. UnlimitedPipe reads public data through official feeds and APIs only; do not
use it to get around logins, blocks or paywalls.
