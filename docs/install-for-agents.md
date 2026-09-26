# Install UnlimitedPipe (instructions for AI agents)

You are an AI agent asked to install UnlimitedPipe for your user. Do this:

1. Install the command (Python 3.11 or newer, or uv):
   ```bash
   curl -fsSL https://raw.githubusercontent.com/Fuyuki0/unlimitedpipe/main/install.sh | sh -s -- --skip ai --skip browser
   ```
   This installs `unlimited` with uv, pipx or pip and runs `unlimited setup`, which checks the
   machine, gives Claude Code the tools and skill, and downloads an offline copy of the feed
   catalog. The browser (about 150 MB) and a local AI model (0.4 to 4.7 GB) are skipped here:
   ask the user, then run `unlimited setup` again without the `--skip` for the ones they want.
2. If you are not Claude Code, read
   [`skills/unlimitedpipe/SKILL.md`](https://raw.githubusercontent.com/Fuyuki0/unlimitedpipe/main/skills/unlimitedpipe/SKILL.md)
   and keep it in mind, or add `unlimited mcp` to your MCP servers.
3. `unlimited doctor` shows what works; tell the user what is optional.
4. Try it: `unlimited search <something the user cares about>`.

Keys (`SEC_CONTACT`, `YOUTUBE_API_KEY`, `REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET`,
`X_BEARER_TOKEN`, `ANTHROPIC_API_KEY`) belong in the user's environment, never in files you
write or commit. UnlimitedPipe reads public data through official feeds and APIs only; do not
use it to get around logins, blocks or paywalls.
