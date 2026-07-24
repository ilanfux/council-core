# Council Core — MCP server (use it from the Claude Desktop app)

The council is a **local developer tool**: it dispatches each persona to a real
model backend (Cursor or provider APIs) from your machine, using your keys. The
MCP server exposes that to MCP clients — most usefully the **Claude Desktop app**
— so you can convene a council from a normal chat while the **real multi-model
dispatch still runs locally**. The client only sends a brief and receives a
verdict; your API keys never leave the server.

> This is the honest way to get "council from the Claude app." It is NOT the host
> chat model role-playing every persona (that would be one model wearing seven
> hats, which defeats the cross-family diversity the council exists for).

## What it exposes

Three tools:
- **`convene_council`** — run a council. Args: `brief` (required), `pack`, `mode`,
  `stakes`, `dynamic`, `cwd`, `documents` (`"label::/abs/path"` list),
  `inline_documents` (`{name: text}`), `require_cursor`. Returns the verdict
  markdown **plus** a structured projection (status, cascade tier, warnings,
  model assignments, per-advisor results).
- **`list_packs`** — packs, their modes, and grounding, so the model can pick.
- **`check_backends`** — which backends have credentials ready on the server.

A `choice_required` route comes back as structured data — the calling Claude
picks a pack and calls again; the server never prompts.

## Setup (Claude Desktop, Windows)

1. **Install with the mcp extra** (also registers the `council-mcp` command):
   ```bash
   pip install -e "C:\council[mcp]"      # dev install from the repo
   # or, once published:  pip install "council-core[mcp]"
   ```
2. **Add the server** to `%APPDATA%\Claude\claude_desktop_config.json`:
   ```json
   {
     "mcpServers": {
       "council": {
         "command": "python",
         "args": ["-m", "council_core.mcp_server"]
       }
     }
   }
   ```
   Using `python -m council_core.mcp_server` avoids PATH issues with the console
   script. (If you prefer the script and it's on PATH, use
   `"command": "council-mcp"` with no args.)
3. **Restart Claude Desktop.**

### Credentials

The server reads keys from its environment (never from a file). Claude Desktop
launches the server with your user environment, so the free-backend keys already
set as **user environment variables** (`GEMINI_API_KEY`, `GROQ_API_KEY`,
`OPENROUTER_API_KEY`, `OLLAMA_API_KEY`) are picked up automatically. If
`check_backends` shows them not-ready, make sure they're set at the *user* level
(not just the current shell) and restart Claude Desktop.

## Verify

In a Claude Desktop chat: **"use the council server to check backends"** →
expect `google/groq/openrouter/ollama` = `ready`. Then **"list the council
packs"**, then **"convene a council on \<your question\>"**.

## Notes / limits

- **Run time:** a full council is many model calls (~30s–minutes). Prefer
  `stakes: quick` for fast checks; `thorough` adds specialists + peer review.
- **Grounded Cursor packs (`*_cursor`)** read files under `cwd`; when using them
  via MCP, pass documents through `cwd` or use a provider pack — the run warns if
  documents aren't reachable by grounded agents.
- **Secrets stay server-side** — only briefs and verdicts cross the MCP boundary.

## Reaching claude.ai (web) instead

The stdio server above serves **local** clients (Claude Desktop, Claude Code).
The claude.ai **website** only accepts **remote** connectors, which needs the
server run over HTTPS with auth and registered as a custom connector — a bigger
ops lift (TLS, a token/OAuth, keeping it up). The tool logic is identical; only
the transport and auth differ. Do this only if the website specifically matters.
