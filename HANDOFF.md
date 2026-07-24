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
  - `orchestrator.py` (`run_council`), `format.py`, `cli.py`,
    `config_loader.py`, `metering.py`, `env.py`
- **Packs** (`src/council_core/builtin_packs/`): `dev` (12 advisors, modes
  review/plan, grounding git_repo), `finance` (6 advisors, mode advise, grounding
  documents, CFO=Chairman, **fail-closed** on Fact/Risk), `career` (14 personas,
  modes strategy/resume/interview/offer, 6 core lenses incl. Skeptic +
  Ghostwriter authenticity pass, grounding documents).
- **Tests**: 40 passing (`pytest`), all with fake backends — deterministic, no
  network. Cover routing, roster selection, pack validation/failure paths,
  dynamic repair (incl. tiny-cap + hostile-field bounding), grounding, output
  contracts, and the orchestrator wiring.
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

## 3. What is MISSING / not yet built

Ordered roughly by importance for "make it a real product."

1. **Skill wrapper** — nothing yet makes the council invokable as an assistant
   *skill*. This is section 4.
2. **Cursor SDK multi-model (grounded)** — the Cursor backend is a **stub**; the
   council currently only runs *provider* backends (plain chat + injected
   context). This is section 5.
3. **LLM router classifier** — `router.py` does deterministic trigger scoring
   only. The optional LLM classifier for ambiguous briefs is a `generate` hook
   that is never wired. Ambiguity currently → `choice_required`.
4. **Draft-only pack promotion** — `council pack draft-from-run <run-id>` (turn a
   good dynamic roster into a reviewable draft pack) is designed in PLAN.md
   Phase 6 but not built.
5. **Document grounding is text-only** — `grounding/documents.py` reads
   `.txt/.md/.csv/.json/.yaml`. No PDF/docx parsing (user must export to text).
6. **Per-pack model diversity resolution** — packs hardcode a model+family+backend
   per persona. There is no runtime "resolve models against what's available +
   enforce cross-family diversity" step like PLAN.md `model_routing` envisions.
   (Dynamic councils DO spread families via `assign_models`.)
7. **`council usage` / budget command** — metering writes `~/.council/usage.jsonl`
   but there is no summary/budget-ceiling CLI (donor had one).
8. **CLI name collision** — both `council-core` and `dev-council-runner` register
   the `council` script. Right now `council` = council-core and the donor is
   reachable via `python -m council`; a reinstall could flip it. Fix by
   uninstalling the donor once it's fully absorbed as the `dev` pack, or rename
   an entry point.
9. **Confidence signals** — intentionally omitted in v1 (see PLAN.md §7). If ever
   added, expose component signals, not a single LLM float.

---

## 4. MISSING PIECE A — make the council work as a "skill that calls different models"

### What "skill" means here

The donor councils are triggered by a **skill file** (`SKILL.md`) that lives in
an assistant's skill directory (e.g. Cursor: `~/.cursor/skills/<name>/SKILL.md`;
Claude Code: a skill under the plugin/skills path). The skill is the *brain* that:

1. Recognizes the user's intent ("review my resume", "should I take this offer").
2. **Gathers the materials** into a brief (and, for document/grounded packs,
   collects file paths).
3. **Shells out to the CLI** — `council run --pack … --brief … --ground …`.
4. Presents the returned verdict markdown to the user.

The engine already exposes exactly the surface a skill needs (a CLI that takes a
brief + pack + grounding args and returns markdown + an optional JSON manifest).
**What's missing is the skill file(s) and the glue.**

### What to build

1. **A `SKILL.md`** (one per target assistant, or one generic). It should:
   - Describe *when* to trigger (keywords: career/offer/resume, finance/pension/
     tax, code review/plan, or "convene a council on …").
   - Instruct the assistant to build a brief and detect the right `--pack` and
     `--mode`, or pass `--dynamic` for novel topics. (It can let the engine route
     by omitting `--pack`, and handle a `choice_required` result by asking.)
   - For grounded/document packs, instruct it to collect file paths and pass
     `--ground "documents=label::path"` (finance/career) or run from the repo dir
     for `dev`.
   - Call the CLI and render the markdown verdict; optionally save the manifest.
2. **A stable, machine-friendly CLI contract.** Add `--json` output (return the
   `CouncilResult`/manifest as JSON) so a skill can parse status/warnings, not
   just scrape markdown. Today `--manifest <path>` writes JSON; a `--json`
   stdout mode would be cleaner for skills.
3. **Non-interactive routing already works**: `run_council` returns
   `choice_required` without prompting; the CLI asks only on a TTY, else exits 2
   with guidance. A skill should pass `--pack`/`--dynamic` explicitly (it knows
   the intent) to avoid the ambiguity round-trip.
4. **Install/registration doc**: where the skill file goes for Cursor vs Claude
   Code, and that `council` must be on `PATH` (it is, via the console script).

**"Calls different models" is already true** at the pack level: each persona in a
pack declares its own `backend`+`model`+`family`, dispatch groups by backend and
runs them concurrently, and peer review picks a cross-family reviewer. The skill
doesn't choose models — it chooses the *pack/mode/brief*; the pack chooses the
models. So the skill layer is purely orchestration glue around the existing CLI.

### Fast path

The donor repos already contain working `SKILL.md` files (dev-council ships one;
career-council-repo's `GUIDE.md` references `~/.cursor/skills/career-council/
SKILL.md`). **Port one of those**, changing the invoked command to
`council run --pack <id> …`. That is the shortest route to a working skill.

---

## 5. MISSING PIECE B — Cursor SDK for grounded multi-model

### Why Cursor matters

Provider backends (openai/anthropic/google + the free gateways) are **plain chat
calls**: they cannot browse the repo, so `dispatch.py` injects a bounded
grounding snapshot into their prompt. The **Cursor SDK backend is different and
better for code**: each persona runs as a **grounded local agent** that can
Read/Grep/Glob the real repository and cite `file:line`. Crucially, Cursor gives
you **multiple model families through one key** (GPT/Codex + Claude + Gemini +
Composer), so a fully diverse council needs only a single `CURSOR_API_KEY`.

### Current state

`council_core/backends/cursor.py` exists and is registered, but
`council_core/sdk_client.py` is a **stub**: `run_agents_batch` and
`discover_models` raise `SdkUnavailableError`. So selecting `backend: cursor`
today does not actually run.

### What's required to make it work

The donor has a complete, battle-tested implementation at
`C:\dev-council\src\council\sdk_client.py` (270 lines). **Port it**, rebasing
imports `council.*` → `council_core.*`. Key things it handles that you must
preserve:

1. **Async + Windows Proactor loop (critical).** The SDK's *sync* bridge uses
   `select.select()` on subprocess pipes, which fails on Windows
   (`WinError 10038`). You **must** drive the *async* API and, on Windows, set
   `asyncio.WindowsProactorEventLoopPolicy()` before `asyncio.run()`. This is the
   single biggest gotcha — the donor's `_run_async()` does exactly this.
2. **`run_agents_batch(tasks, cwd, api_key)`** — launch one `AsyncClient` bridge,
   `asyncio.gather` the agents (`AsyncAgent.prompt(...)` with
   `AgentOptions(api_key, model, local=LocalAgentOptions(cwd=cwd))`), preserve
   task order, and normalize results into `AgentOutcome` (distinguish
   `startup_error` vs run `error`; one failure never sinks the batch).
3. **`build_model_selection(model_id, params)`** — a plain id string, or a
   `ModelSelection` dict when params are set (GPT/Codex `reasoning`; Claude
   `effort`/`thinking`; Gemini none).
4. **`discover_models(api_key) → (available_ids, param_catalog)`** — call
   `client.list_models(...)` once; extract model ids and each model's supported
   params/values. This powers two engine features the provider path skips:
   - **`resolve_models`**: fall back any configured Cursor model id the account
     can't use to a safe default (never invent a slug).
     — *Not yet ported into council_core; add it to `pack.py`/`config_loader.py`.*
   - **param validation**: drop a family-specific param a model doesn't support
     (e.g. Claude `effort` on a GPT model) with a warning instead of failing.
5. **Dependencies**: `pip install cursor-sdk` and set `CURSOR_API_KEY`. The
   backend's `grounded = True` flag already tells `dispatch.py` to NOT inject
   context (the agent reads the repo itself) — that path is implemented and
   tested; only the SDK client underneath is stubbed.

### Concrete steps to enable Cursor multi-model

1. Replace `council_core/sdk_client.py` with the donor's implementation (rebased
   imports). Keep the `SdkUnavailableError` subclass of `BackendError`.
2. Port the donor's model-resolution logic (`resolve_models`,
   `validate_model_params` from `C:\dev-council\src\council\config_loader.py`)
   into council_core, and call it in `orchestrator.run_council` **only when a
   selected persona/chairman uses `backend: cursor`** (mirror the donor's
   `_cursor_needed_for` gate so a pure-provider pack never needs a Cursor key).
3. Add a `dev`-pack variant (or user override) whose personas use
   `backend: cursor` with Cursor model ids (`gpt-5.x`, `claude-*`,
   `gemini-*`, `composer-*`) so a diverse grounded council runs from one key.
4. Add a `council models` subcommand (port from donor) to list usable Cursor
   models and show per-persona resolution — useful for debugging assignments.
5. Test: because it needs a live key + network, gate it behind an integration
   marker; keep the deterministic suite fake-backed as-is.

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
