# Council Core — Handoff & Continuation Prompt

> **Purpose of this file.** A self-contained briefing for a fresh Claude session
> (or engineer) picking up the `council_core` project. Read this top-to-bottom
> and you have everything needed to continue: what the system is, what's built,
> how to run it, what's missing, and — in detail — the two things most asked
> about: **(A) making the council usable as a "skill" that calls different
> models**, and **(B) wiring the Cursor SDK so a single council can run each
> persona on a different AI model, grounded in a repo.**
>
> Companion doc: [`PLAN.md`](PLAN.md) holds the full architecture rationale and
> the two external design reviews. This file is the operational handoff.

---

## 1. What the council is

A **generic, multi-model "council" engine**. A council convenes several *advisor*
personas — each grounded and run on a **different model family** — dispatches the
brief to all of them, anonymizes and peer-reviews their answers, and has a
separate **Chairman** synthesize one decisive verdict. Running advisors on
de-correlated model families is the whole point: it breaks up shared blind spots.

Everything domain-specific lives in a **pack** (personas, prompts, grounding
source, output contract, tiers, failure policy). The engine has **no domain
conditionals**. Two ways a roster is chosen:

- **Predefined pack** — a known domain (`dev`, `career`, `finance`).
- **Dynamic council** — a novel topic: a `PersonaArchitect` designs a roster on
  the fly (capped at 5: Chairman + Risk + Fact + up to 2 SMEs).

This project **consolidates three previously separate councils** into one engine.
It is a fresh rewrite; the originals are untouched donors.

### Repo map (all on this machine)

| Path | Role |
|---|---|
| **`C:\council`** | **This project.** Package `council_core`, CLI `council`. |
| `C:\dev-council` | Donor engine (dev code-review). Package `dev-council-runner`, `python -m council`. Source of the engine + the `dev` pack. |
| `C:\retirement_council` | Source of the `finance` pack (6 YAMLs). |
| `C:\Job_Search_2026\career-council-repo` | Source of the `career` pack (package `career-council-runner`, CLI `career-council`). |
| `C:\Second_Brain_Career_Council` | **Not merged** — LangGraph+Neo4j+MCP, different stateful architecture. |

---

## 2. What is DONE (as of this handoff)

A working, tested engine plus three real packs. All three packs are faithful
ports of their true sources (dev←dev-council, finance←retirement_council,
career←career-council-repo).

- **Engine** (`src/council_core/`): typed contracts (dataclasses internally,
  Pydantic at boundaries), pipeline
  `Route → Build Council → Gather Grounding → Dispatch → Peer Review → Chairman → Validate`.
  Modules:
  - `input.py` (PersonaSpec, CouncilRequest, AgentOutcome, AdvisorResult…)
  - `spec.py` (CouncilSpec: **Chairman is a separate field, not an advisor**)
  - `pack.py` (pack.yaml manifest → normalized `PackDefinition`; discovery order
    explicit path → `~/.council/packs/` → built-in; path-containment guard)
  - `router.py` (deterministic trigger scoring → `pack | dynamic | choice_required`;
    **never does UX**)
  - `roster.py` (`build_pack_council`, `build_dynamic_council`)
  - `persona_architect.py` (`RoleDraft` → deterministic repair → trusted
    `compile_persona` → model assignment)
  - `grounding/` (typed `GroundingBundle`; providers: `git_repo`, `documents`,
    `null`)
  - `prompts/` (file-based, versioned-by-hash templates; pack-overridable)
  - `output.py` (declarative, schema-validated verdict contracts)
  - `policy.py` (`ExecutionPolicy`: fail-closed vs degrade)
  - `dispatch.py`, `peer_review.py`, `chairman.py` (the unchanged core)
  - `backends/` (registry + `cursor`, `openai`, `anthropic`, `google`)
  - `result.py` (`CouncilResult` envelope) + `manifest.py` (Pydantic `RunManifest`)
  - `orchestrator.py` (`run_council`), `format.py` (markdown + `--json`), `cli.py`,
    `config_loader.py`, `metering.py`, `env.py`
  - `sdk_client.py` (real Cursor SDK client), `model_resolve.py` (Cursor→provider→UI
    cascade), `router_classifier.py` (opt-in LLM router), `pack_promote.py`
    (`draft-from-run`), `skill_install.py` (skill install command)
- **Packs** (`src/council_core/builtin_packs/`) — **6 total**: `dev` (12 advisors,
  modes review/plan, grounding git_repo), `finance` (6 advisors, mode advise,
  grounding documents, CFO=Chairman, **fail-closed** on Fact/Risk), `career` (14
  personas, modes strategy/resume/interview/offer, 6 core lenses incl. Skeptic +
  Ghostwriter authenticity pass, grounding documents), plus **`dev_cursor` /
  `finance_cursor` / `career_cursor`** — the same rosters mapped onto `backend:
  cursor` so one `CURSOR_API_KEY` runs GPT/Codex + Claude + Gemini + Composer as
  grounded agents.
- **Tests**: **79 passing, 1 skipped** (`pytest`), all with fake backends —
  deterministic, no network. The 1 skip is a live-Cursor integration test
  (`--run-integration`). Cover routing, roster selection, pack validation/failure
  paths, dynamic repair, grounding, output contracts, orchestrator wiring, the
  Cursor model-resolution cascade, `--json`, skill install, and promotion.
- **Reviewed**: the old dev-council was run as an external reviewer in a loop
  (rounds A/B/C + a verification pass). Every real bug was fixed; security
  findings inapplicable to a local single-user CLI were discarded with rationale.
  See git history (`5d6c027`, `8b4641e`, `390878d`, `eeb57cf`).
- **Run manifest**: every run emits a replayable record (plan/input
  reproducibility — NOT identical LLM output; see PLAN.md §9).

### How to run it TODAY

```bash
# from C:\council, package installed as `council` (console script)
council backends          # show which backends have credentials
council packs             # list dev / finance / career

# a real run (provider backends; free keys already set in this env):
council run --pack finance --stakes standard \
  --ground "documents=payslip::C:\path\to\payslip.txt" \
  --brief "Should I withdraw my keren hishtalmut for a down payment?"

council run --pack career --mode resume --brief-file brief.txt --manifest run.json
council run --dynamic --brief "How should we price carbon credits for a startup?"
```

**Backends currently ready in this environment** (free, OpenAI-compatible):
`google`, `groq`, `openrouter`, `ollama`, `github`. NOT ready: `cursor`,
`openai`, `anthropic` (no keys). Config: `src/council_core/defaults/backends.yaml`
(+ user override `~/.council/backends.yaml`). Credentials come from env vars only.

---

## 3. Status — recently built, and what remains

The initial handoff listed the items below as "missing." **All the core ones are
now built, reviewed, and fixed** (Cursor SDK enablement + product backlog). Tests:
79 passing, 1 integration skip.

**DONE (was missing):**
- **Cursor SDK multi-model (grounded)** — the stub is replaced with a real client;
  a diverse grounded council runs from one `CURSOR_API_KEY`. See §5.
- **Skill wrapper** — canonical `SKILL.md` + `council skill install`. See §4.
- **LLM router classifier** — built but **opt-in** (`router.use_classifier: false`
  by default; deterministic scoring otherwise).
- **Draft-only pack promotion** — `council pack draft-from-run` / `pack validate`
  (`pack_promote.py`); produces a draft for human review, never auto-installs.
- **PDF/docx grounding** — `grounding/documents.py` (extras `council-core[docs]`:
  pypdf + python-docx).
- **`council usage`** — metering summary + soft budget ceiling.
- **Cursor model resolution + param validation** — `model_resolve.py` (§5 cascade).

**Still open / intentional:**
1. **CLI name collision** — `council-core` and donor `dev-council-runner` both
   register `council`. Currently `council` = council-core; donor via
   `python -m council`. Resolve by uninstalling the donor once it's fully absorbed
   as the `dev` pack.
2. **Confidence signals** — intentionally omitted (PLAN.md §7); if added, expose
   component signals, not a single LLM float.
3. **General cross-provider diversity policy** (PLAN.md `model_routing`, Phase 8) —
   deferred. The Cursor cascade covers multi-model-from-one-key; a runtime
   "resolve provider packs against what's available + enforce cross-family
   diversity" step is still unbuilt (provider packs hardcode model/family/backend).
4. **Two minor review notes** (neither blocking): a now-unused `provider_pool`
   param in `model_resolve._resolve_ui_model` (cosmetic); and the live Cursor
   smoke run is only verifiable with a real `CURSOR_API_KEY` (reported working:
   `dev_cursor` → 4/4 advisors on Cursor).

---

## 4. Feature A — the council as a "skill" (BUILT)

A skill is a `SKILL.md` the assistant (Cursor / Claude Code) reads to know *when*
to convene a council, how to build the brief, which pack/mode to pick, and to
shell out to the `council` CLI and render the verdict.

**How it works now:**
- **Canonical source:** `src/council_core/skills/council/SKILL.md` (single file,
  shipped as package data — do not re-duplicate it).
- **Install:** `council skill install` copies it into `~/.cursor/skills/council/`
  and/or `~/.claude/skills/council/` (and a `--project` variant writes into the
  repo's `.cursor`/`.claude`). Those host copies are *targets*, generated on
  demand — never edited or committed.
- **Machine-readable output:** `council run --json` returns the `CouncilResult`
  (route, model assignments, cascade tier, status, warnings, verdict, per-advisor
  results, and the rendered markdown) so a skill parses structured data instead of
  scraping text. `--manifest <path>` still writes the full `RunManifest`.
- **Routing:** the skill passes `--pack`/`--mode` (or `--dynamic`) explicitly when
  it knows intent; a `choice_required` result is the CLI's to resolve (asks on a
  TTY, exits 2 non-interactively).

**"Calls different models" is intrinsic:** each persona declares its own
`backend`+`model`+`family`; dispatch groups by backend and runs them concurrently;
peer review picks a cross-family reviewer. The skill picks the *pack/mode/brief* —
the pack (and, for Cursor, the resolution cascade in §5) picks the models.

---

## 5. Feature B — Cursor SDK grounded multi-model (BUILT)

### Why Cursor matters

Provider backends (openai/anthropic/google + free gateways) are **plain chat
calls**: they can't browse the repo, so `dispatch.py` injects a bounded grounding
snapshot. The **Cursor SDK backend runs each persona as a grounded local agent**
that reads the real repo and cites `file:line`, and it exposes **multiple model
families from one key** (GPT/Codex + Claude + Gemini + Composer). So a fully
diverse grounded council needs only a single `CURSOR_API_KEY`.

### What's built

- **`sdk_client.py`** — real client ported from the donor. Preserves the critical
  gotcha: it drives the SDK's **async** API and sets
  `asyncio.WindowsProactorEventLoopPolicy()` on Windows (the sync bridge fails on
  pipes with `WinError 10038`). Provides `run_agents_batch` (one async bridge +
  `asyncio.gather`, order-preserving, `startup_error` vs run `error`),
  `build_model_selection` (id string or `{id, params:[{id,value}]}`), and
  `discover_models → (ids, param_catalog)`.
- **`model_resolve.py`** — a resolution **cascade**, gated by `cursor_needed_for`
  so pure-provider packs never touch Cursor:
  - **A · Cursor:** validate each cursor model id against the live catalog (fall
    back unusable ids to `default_model`, never invent a slug); drop
    family-specific params a model doesn't support.
  - **B · providers:** if Cursor is unusable, remap cursor personas onto ready
    `dynamic_pool` provider assignments (round-robin for family spread).
  - **C · UI model:** last resort — force the skill's `--ui-model` /
    `COUNCIL_UI_MODEL` (never implicitly `cursor`).
  - The chosen tier is reported as `result.cascade_tier` + `model_assignments`.
- **`--require-cursor` / `request.require_cursor`** — when set, a Cursor-needed
  roster that can't reach Cursor returns a **non-convened, `FAILED`** result with
  a clear "set CURSOR_API_KEY" message instead of silently downgrading. Without
  the flag, a downgrade to providers/UI prints a prominent banner in the verdict.
- **`dev_cursor` / `finance_cursor` / `career_cursor` packs** — the three rosters
  on `backend: cursor` with real Cursor model ids (`gpt-5.x`, `claude-*`,
  `gemini-*`, `composer-2.5`).
- **`council models`** — lists usable Cursor ids and per-persona resolution.

### To run it

`pip install 'council-core[cursor]'` and set `CURSOR_API_KEY`, then e.g.
`council run --pack dev_cursor --mode review --cwd <repo> --require-cursor
--brief "…"`. The live path is covered by an integration-marked test (skipped
unless `--run-integration` + a key). Reported working: `dev_cursor` → 4/4
advisors on Cursor, `finance` still runs with no Cursor key (cascade `unchanged`).

---

## 6. Architecture invariants (do not break these)

- A new domain must be addable **without editing** `orchestrator.py`,
  `dispatch.py`, `peer_review.py`, or `chairman.py`. Domain behavior enters only
  through a `PackDefinition` and its adapters.
- **Chairman is a distinct pipeline role**, never a dispatched/peer-reviewed
  advisor (`CouncilSpec{advisors, chairman}`).
- **Router returns a decision; the caller does UX.** Never prompt inside the
  router or orchestrator.
- **Dynamic personas are compiled from constrained `RoleDraft`s** by the trusted
  `compile_persona` — the architect never emits a raw system prompt and never
  picks models/backends. Field text is length-bounded.
- **Pydantic only at boundaries** (`pack.yaml`, `RoleDraft`, `RunManifest`,
  external input). Engine internals stay dataclasses.
- **Credentials from environment only.** Never write a key to any file.
- **Metering never breaks a run** and never logs prompt/response text.

---

## 7. Suggested next-session task list

Most of the original backlog is done (Cursor SDK + cascade, `*_cursor` packs,
skill install, `--json`, `council usage`, `draft-from-run`, optional LLM
classifier behind `router.use_classifier`, PDF/docx via `[docs]` extra). Remaining
polish is optional.

Verification for any change: `python -m pytest -q` (must stay green; default
suite excludes `@pytest.mark.integration`). Live Cursor:

```bash
python -m pytest -q --run-integration -m integration
```

### Cursor verified (2026-07-24)

Manual live smoke on this machine with `CURSOR_API_KEY` set:

- `council run --pack dev_cursor --mode review --stakes standard --require-cursor`
  → cascade tier `cursor`, **4/4** advisors ok across multiple families
  (Codex / Composer / GPT), Chairman verdict ok, status `completed`.
- Provider-only `council run --pack finance` with no Cursor requirement →
  cascade tier `unchanged`, convened successfully (document grounding warning
  only when no files passed).
- `--require-cursor` fails clearly when Cursor discovery is unavailable (no
  silent provider downgrade).
- Default `python -m pytest -q` skips `@pytest.mark.integration`; live path:
  `python -m pytest -q --run-integration -m integration`.
