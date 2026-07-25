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

## Remote: use it from your phone (claude.ai app)

Your phone runs the **cloud** Claude, which can't reach the local stdio server.
For the phone you expose the council as a **remote connector**: run the same
server over HTTP behind a tunnel, then register it on your Claude account (a
connector is account-level, so it appears in the mobile app too). The multi-model
dispatch still runs on your machine/host — only briefs and verdicts cross the
network.

> ⚠️ Exposing this runs the council on **your** keys for anyone who can reach it.
> A bearer token is **required** (the server refuses to start HTTP without one),
> and it binds `127.0.0.1` by default so only the tunnel can reach it.

**Steps (cloudflared tunnel from your PC — free; PC must stay on):**

1. **Pick a strong token** and set it, plus run the HTTP server:
   ```bash
   set COUNCIL_MCP_TOKEN=<paste a long random string>
   council-mcp --http --port 8787       # or: python -m council_core.mcp_server --http
   ```
2. **Expose it** with a tunnel (install `cloudflared` first):
   ```bash
   cloudflared tunnel --url http://127.0.0.1:8787
   ```
   It prints a public `https://<random>.trycloudflare.com` URL.
3. **Register it in claude.ai → Settings → Connectors** as a custom/remote MCP
   connector, using that HTTPS URL. Supply the bearer token where the connector
   asks for auth. Once added to your account it's available in the **Claude app
   on your phone**.
4. On the phone: *"use the council connector to convene a council on …"*.

**Honest caveats (verify on your side):**
- **This transport path isn't runtime-verified here** (needs a live `mcp` +
  `uvicorn` + a running tunnel). The token/auth logic is unit-tested; the ASGI
  wiring follows the FastMCP API and may need a small tweak for your installed
  `mcp` version (the method is `streamable_http_app()` / `http_app()`).
- **claude.ai custom-connector auth** may expect **OAuth** rather than a static
  bearer header — check the current connector requirements in your claude.ai
  settings. If it won't accept a bearer token directly, put the server behind an
  edge that does auth (e.g. **Cloudflare Access**) and let the tunnel handle it.
- **Uptime:** a `trycloudflare` URL and your PC must both be up when you want it
  from the phone. For always-on, run the server on a small VM and use a stable
  hostname instead of the throwaway tunnel URL.
- **Documents** you send from the phone travel to the server — fine on your own
  box; think twice for anything sensitive.

For a quick brainstorm with **zero setup** (works on the phone today but is a
single model role-playing the roster — no real cross-family diversity), that's a
different "in-chat" skill, not this server.
