# Kickoff prompt — plan the remaining work on Council Core

> Paste everything below the line into the AI model (Cursor agent, Claude Code,
> etc.). It works from the repo at `C:\council`.

---

You are picking up an in-progress project called **Council Core** at
`C:\council` (Python package `council_core`, CLI `council`).

**What it is (highlight):** a generic, multi-model "council" engine. It convenes
several advisor personas — each run on a *different* AI model family — dispatches
a brief to all of them, anonymizes and peer-reviews their answers, and a separate
Chairman synthesizes one decisive verdict. Running advisors on de-correlated
model families is the whole point: it breaks up shared blind spots. All
domain-specific behavior lives in "packs" (`dev`, `finance`, `career`); the
engine itself is domain-neutral. It's already built and tested (40 passing tests)
and runs today on free OpenAI-compatible backends (google/groq/openrouter/ollama).

**Read these first, in full, before proposing anything:**
1. `C:\council\HANDOFF.md` — the complete operational briefing: what's done,
   what's missing, how to run it, and detailed notes on the two open gaps.
2. `C:\council\PLAN.md` — the architecture, locked design decisions, and the
   invariants you must not break.
3. Skim the code under `C:\council\src\council_core\` to confirm the current
   state (especially `backends/cursor.py`, `sdk_client.py`, `orchestrator.py`,
   `dispatch.py`, `pack.py`).

**Your task: produce an implementation PLAN (not code yet) for the missing work,
with the top priority being: make the council run on the Cursor SDK so a single
council can use MULTIPLE AI models (GPT/Codex + Claude + Gemini + Composer) from
one `CURSOR_API_KEY`, with each persona as a grounded local agent that reads the
real repo and cites `file:line`.**

Key facts about that priority (verify against the code and HANDOFF.md §5):
- The Cursor backend (`council_core/backends/cursor.py`) is registered but its
  engine underneath, `council_core/sdk_client.py`, is a **stub** that raises.
- A complete, working reference implementation exists in the donor repo at
  `C:\dev-council\src\council\sdk_client.py` (270 lines) — study it. Note the
  **critical Windows gotcha**: you must drive the SDK's *async* API and set
  `asyncio.WindowsProactorEventLoopPolicy()` (the sync bridge fails on Windows
  pipes with `WinError 10038`).
- Enabling Cursor also needs model discovery + `resolve_models` (fall back
  unusable model ids, never invent a slug) + family-specific param validation,
  and a `_cursor_needed_for` gate so pure-provider packs never require a Cursor
  key. These exist in the donor's `sdk_client.py` and `config_loader.py`.

**The plan you produce must include:**
1. A phased breakdown, **Cursor SDK multi-model first**, then the other missing
   items from HANDOFF.md §3 (skill wrapper, LLM router classifier, draft-from-run
   promotion, `council usage`, CLI name collision, PDF/docx grounding) ranked by
   value.
2. For each phase: concrete deliverables, the exact files to add/change, the main
   risks/gotchas, and an acceptance gate + the tests required before advancing.
3. Explicit respect for the architecture invariants in PLAN.md and HANDOFF.md §6
   (Chairman is separate from advisors; router does no UX; dynamic personas are
   compiled from constrained drafts; Pydantic only at boundaries; credentials
   from env only; a new domain must not require editing the engine core).
4. A verification strategy: keep the deterministic fake-backend test suite green
   (`python -m pytest -q`, 40+), plus a live smoke run, plus how to gate the
   Cursor path (needs a live key + network) behind an integration marker.

Do NOT start writing code until the plan is reviewed and approved. Present the
plan first. If anything in the docs is ambiguous or looks stale versus the code,
call it out rather than guessing.
