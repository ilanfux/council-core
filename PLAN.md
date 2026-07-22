# Council Core — Consolidation Plan (rev. 2)

One generic multi-model **council** engine. A council convenes several advisor
personas (each grounded and run on a different model family), dispatches the
brief to all of them, anonymizes and peer-reviews their responses, and has a
**separate Chairman** synthesize a decisive verdict. Everything domain-specific
— personas, prompts, grounding source, model policy, output contract, failure
policy — is packaged as a **pack**. The engine contains no domain-name
conditionals.

Two ways a roster is chosen:

- **Predefined pack** — a known domain (`dev` / `career` / `finance`) with a
  curated, optimized roster.
- **Dynamic council** — a novel topic where a `PersonaArchitect` designs a
  roster on the fly, capped at 5 personas.

> Revision history: rev. 2 folds in two external architecture reviews plus
> code-grounded corrections after reading the full donor engine. Key deltas from
> rev. 1: Chairman modeled as a distinct pipeline role (not a roster member);
> versioned `pack.yaml` manifest; typed grounding + typed run envelope; router
> returns a decision and never does UX; dynamic personas compiled from
> constrained `RoleDraft`s by a trusted compiler; explicit per-pack
> `ExecutionPolicy`; a first-class reproducible run manifest; built-in packs
> moved inside the package; Phase 0 "characterize the donor first."

---

## 1. Provenance

- **Engine donor:** `C:\dev-council` — cleanest, most complete existing runner.
  Copied here and de-coupled from its dev-only assumptions. Left untouched at
  source; used as a parity/characterization reference in Phase 0–2.
- **Finance pack:** the six YAMLs in `C:\retirement_council` become the
  `finance` built-in pack. Left untouched at source.
- **Career pack:** ported from the older, simpler Career Council at
  `C:\Job_Search_2026\career-council-repo` (package `career-council-runner`, a
  documented sibling of dev-council). Its 6 core lenses (Career Strategist,
  Recruiter, Hiring Manager, Candidate Advocate, Skeptic→`risk_auditor`,
  Ghostwriter Detector→`authenticity_auditor`) and 4 modes (strategy/resume/
  interview/offer) are now `builtin_packs/career`, mapped onto free cross-family
  backends. Left untouched at source.
- **Not merged:** `C:\Second_Brain_Career_Council` (LangGraph + Neo4j +
  ingestion + MCP) is a different, stateful architecture and stays separate. It
  may later consume this core as a library.

---

## 2. Locked decisions

1. **Fresh rewrite** — new repo `C:\council` (package `council_core`); existing
   projects are copied from, never overridden.
2. **Chairman is a distinct pipeline role, not an advisor.** Only advisors are
   dispatched and peer-reviewed; the Chairman receives their completed
   artifacts. This formalizes a separation the donor engine *already* enforces
   (`select_personas()` never returns the chairman; `run_chairman()` is its own
   stage) — it is a hardening, not a behavior change.
3. **Dynamic council cap = 5 personas total:** Chairman + Risk/Critical Reviewer
   + Fact/Evidence Analyst + up to 2 SMEs ⇒ normally **4 dispatched advisors +
   1 Chairman**.
4. **Router never performs UX.** It returns a structured decision (including
   `choice_required`); the CLI/API/adapter does any asking. Non-interactive
   callers get a structured choice-required result, never a blocking prompt.
5. **Dynamic personas are compiled, not free-generated.** The `PersonaArchitect`
   emits constrained `RoleDraft`s; a trusted deterministic `PersonaCompiler`
   turns them into executable `PersonaSpec`s. The architect never emits a raw
   system prompt and never chooses models/backends/retries/budgets/tools.
6. **All packs normalize to one `PackDefinition`** loaded via a versioned
   `pack.yaml`. No engine module contains `if pack == "finance"`.
7. **Typed at the boundaries:** grounding results, the run-result envelope, and
   the persisted run manifest are typed. Verdicts are pack-contract-defined but
   schema-validated (never arbitrary dicts).
8. **No confidence number in v1** (see §7).
9. **Fail-closed for high-stakes packs** on missing mandatory roles (see §8).

---

## 3. Architectural invariants

The abstraction succeeds only if **a new domain can be added without changing**
`orchestrator.py`, `dispatch.py`, `peer_review.py`, or `chairman.py`. Concretely:

- The pipeline stays: `Route → Build Council → Gather Grounding → Dispatch →
  Peer Review → Chairman → Validate Output`.
- All new capability (routing, dynamic generation) lives **before** dispatch.
  The proven `dispatch → peer_review → chairman` core stays ~unchanged.
- Domain behavior enters only through a `PackDefinition` and the adapters it
  names (grounding provider, prompt set, output contract, execution policy).
- Every run emits a reproducible **run manifest** (§9).

---

## 4. Target layout

```
C:\council\
  pyproject.toml
  src/council_core/
    __init__.py  __main__.py  cli.py
    orchestrator.py          # was runner.py — adds Router + Roster stages up front
    input.py                 # PersonaSpec, CouncilRequest, AdvisorResult, ... (dataclasses)
    result.py                # CouncilResult envelope + StageOutcome (dataclasses)
    manifest.py              # RunManifest (Pydantic; persisted projection of a run)
    config_loader.py         # engine/runtime config only (backends, budget) — NOT packs
    dispatch.py              # grounding + prompts INJECTED, not imported
    peer_review.py  chairman.py  metering.py  format.py  env.py
    sdk_client.py            # cursor-specific, optional
    backends/                # copied verbatim from dev-council
    grounding/               # PACKAGE (was a single module in rev.1)
      __init__.py  protocol.py  bundle.py  git_repo.py  documents.py  null.py
    prompts/                 # PromptSet loader + base templates (versioned)
    pack.py                  # PackDefinition + discover/load/normalize/validate (one module)
    router.py                # Router: CouncilRequest -> RouteDecision (no UX)
    roster.py                # RosterProvider + PackRoster + DynamicRoster
    persona_architect.py     # PersonaArchitect (RoleDraft) + PersonaCompiler + repair
    policy.py                # ExecutionPolicy + degraded-mode logic
    builtin_packs/           # built-in packs SHIP INSIDE the package (importlib.resources)
      dev/     pack.yaml  personas.yaml  modes.yaml  prompts/
      finance/ pack.yaml  personas.yaml  routing.yaml  tiers.yaml
               output_contract.yaml  model_routing.yaml  onboarding.yaml  prompts/
      career/  pack.yaml  personas.yaml  modes.yaml  prompts/
  tests/
    characterization/  prompt_parity/  smoke/  fixtures/
```

**Pack resolution order:** explicit `--pack-path` → user pack dir
(`~/.council/packs/`) → `builtin_packs/` (via `importlib.resources`). This makes
`council-core` reusable without editing the installed package.

> Scaffold delta from rev. 1: the repo-root `packs/` directory is replaced by
> `src/council_core/builtin_packs/`; `profile.py` becomes `pack.py`; `grounding`
> becomes a package.

---

## 5. Contracts

Typed models. **Dataclasses internally**; **Pydantic only at untrusted or
persisted boundaries** (`pack.yaml`, router classifier output, `RoleDraft`,
pack-defined verdict, external CLI/API input, `RunManifest`). Rationale in §10.

### Council shape

```
CouncilSpec {                      # what a run will convene
    advisors: tuple[PersonaSpec]   # dispatched + peer-reviewed
    chairman: PersonaSpec          # separate role; receives advisor+review artifacts
    prompts: PromptSet
    grounding: GroundingProvider
    output_contract: OutputContract
    execution_policy: ExecutionPolicy
}

PersonaSpec {                      # generalized from donor
    key, title
    prompt: str                    # was `lens`; the persona's system prompt/lens
    role_id: str | None            # e.g. "risk_auditor" | "fact_analyst" (mandatory-role tag)
    family, model, capability, core
    triggers: list[str]
    model_params: dict[str,str]
    backend: str                   # default comes from the PACK, not hardcoded "cursor"
}
```

### Pack

```
# pack.yaml (schema_version 1) — the ONLY file the core must know by name
schema_version: 1
id: finance
version: 1.0.0
display_name: Finance Council
routing:   { triggers_file: routing.yaml }
council:   { personas_file: personas.yaml, modes_file: modes.yaml, chairman_id: chairman }
prompts:   { directory: prompts }
grounding: { provider: documents, config_file: grounding.yaml }
output:    { schema: dev_verdict_v1 }        # or { schema_file: output_contract.yaml }
models:    { policy_file: model_routing.yaml }
execution: { policy_file: execution.yaml }

PackDefinition {                   # normalized in-memory form the engine consumes
    id, version, display_name
    triggers, modes, personas, chairman
    prompt_set, grounding_provider
    output_contract, model_policy, execution_policy
}
```

Domain-specific files (`tiers.yaml`, `onboarding.yaml`, …) may still exist; the
core discovers them **through the manifest**, never by hardcoded name. `pack.py`
keeps discovery / loading / normalization / validation as separate functions in
one cohesive module (split into classes later only if it earns it).

### Grounding (typed, synchronous)

```
EvidenceItem { source_id, source_type, title?, content, location?, metadata }
GroundingBundle { items: tuple[EvidenceItem], warnings: tuple[str],
                  token_estimate: int, truncated: bool }

Grounding(Protocol):
    def gather(self, request: GroundingRequest) -> GroundingBundle    # SYNC
```

- **Synchronous** — the donor pipeline is `ThreadPoolExecutor`-based with no
  asyncio; an async grounding call would force an async boundary nothing else
  needs. Revisit only if the whole engine moves to asyncio.
- `GitRepoGrounding` (dev) | `DocumentGrounding` (finance/career) |
  `NullGrounding` (dynamic v1). `NullGrounding` returns an empty bundle with a
  `warning` that no external evidence was available.
- The **Fact Analyst prompt must distinguish** evidence-backed claims, general
  model knowledge, assumptions, and unresolved facts — so a `NullGrounding` run
  cannot present ungrounded assertions as verified.

### Routing

```
RouteDecision {
    kind: "pack" | "dynamic" | "choice_required"
    selected_pack: str | None
    confidence: float             # router's own signal, internal; not the verdict's
    candidates: tuple[RouteCandidate]   # (pack_id, score, reason)
    reason: str
}
```

Router = cheap deterministic trigger scoring first; LLM classifier only for
ambiguous cases. On low confidence → `choice_required`. Overrides `--pack` /
`--dynamic` / `--pack-path` skip routing entirely.

### Dynamic generation

```
RoleDraft {                       # what the architect MAY produce
    role_id, title, objective
    focus_areas: tuple[str]
    questions_to_answer: tuple[str]
    evidence_requirements: tuple[str]
    evaluation_lens: tuple[str]
    adversarial: bool
}                                 # NO model/backend/retry/budget/tool/prompt fields

DynamicCouncilContract {
    required_advisor_roles = ("risk_auditor", "fact_analyst")
    chairman_required = True
    max_total_personas = 5
}
```

Flow: `PersonaArchitect → RoleDrafts → deterministic normalize/repair →
PersonaCompiler (trusted templates) → model assignment (diversity policy) →
CouncilSpec`. The compiler owns the final prompt structure but consumes the
architect's structured specialization so SMEs are not generic. Future
pack-specific compiler/template overlays are allowed without touching the core.

### Output

```
OutputContract  = registered Pydantic model | JSON Schema | declarative section schema
GenericVerdict  {                 # default contract for dynamic councils
    conclusion, key_findings, risks, disagreements, next_actions, limitations
}
```

Packs define their own verdict shape (dev's `SHIP/FIX-THEN-SHIP/RETHINK`,
finance's decision brief), but it is **always schema-validated**. No universal
mandatory verdict schema is imposed.

### Result envelope + manifest

```
CouncilResult {                   # in-memory, dataclass
    route, council, grounding
    advisor_results, peer_reviews
    verdict: PackVerdict
    execution: ExecutionSummary   # status + per-stage StageOutcome
    warnings
}

RunManifest {                     # persisted projection, Pydantic (§9)
    run_id, engine_version, pack_id, pack_version
    prompt_template_versions      # requires templates carry a version/hash (§9)
    route_decision, architect_raw_output, roster_repairs
    final_council_spec, model_backend_assignments
    execution_policy, grounding_source_metadata
    seed, stage_outcomes, metering, output_schema_version
}
```

`format.py` renders `CouncilResult` to markdown/JSON/HTML — presentation only,
no reasoning.

---

## 6. Module disposition (from donor `src/council/`)

| Module | Disposition | Note |
|---|---|---|
| `backends/*` (7) | copy as-is | domain-agnostic |
| `metering.py`, `env.py`, `sdk_client.py` | copy as-is | no dev coupling (sdk_client stays Cursor-only) |
| `format.py` | copy, adapt | render `CouncilResult`; pack-defined sections |
| `peer_review.py` | light | peer-review prompt injected via `PromptSet` |
| `chairman.py` | light | prompt injected; `cwd` → generic grounding ctx |
| `dispatch.py` | medium | inject `Grounding` + `PromptSet`; `diff_scope` → grounding request |
| `config_loader.py` | **split** | engine/runtime config stays here; **pack loading moves to `pack.py`**; drop hardcoded `("plan","review")` |
| `input.py` | medium | `PersonaSpec.lens`→`prompt`, add `role_id`; backend default from pack; add `CouncilRequest` |
| `runner.py` → `orchestrator.py` | rewrite front | Router → RosterProvider → (unchanged) dispatch→peer→chairman → validate |
| `prompts.py` | → files | versioned base templates + per-pack overrides under `prompts/` |
| `context.py` | → adapter | `grounding/git_repo.py` (one `Grounding` impl) |
| — | NEW | `pack.py`, `router.py`, `roster.py`, `persona_architect.py`, `policy.py`, `result.py`, `manifest.py`, `grounding/` pkg |

---

## 7. Confidence stance (refinement)

**No confidence number in v1 — computed or LLM-emitted.** A raw LLM
`confidence: float` is false precision. But a *computed* confidence is also a
trap if it includes **advisor agreement**: cross-family models share training
biases and produce **correlated errors**, so high agreement can mean a shared
blind spot — making a computed confidence highest exactly when the council is
most wrong, defeating the point of a diverse council.

If confidence is ever added, expose the **component signals** (e.g. "3/3
advisors agreed · 2/2 required roles present · evidence coverage: partial")
rather than collapsing them into one authoritative-looking number. The reader
judges; the engine does not manufacture calibrated certainty it doesn't have.

---

## 8. Failure & degraded-mode policy

New surface: the donor tolerates any single advisor failure (captured, never
sinks the run; peer review needs ≥2 usable; chairman failure → fallback digest)
because **no role is structurally required**. Mandatory Fact/Risk roles change
that, so we define an explicit, **pack-configurable** policy:

```
ExecutionPolicy {
    required_successful_roles: set[str]        # e.g. {"risk_auditor","fact_analyst"}
    on_missing_required_role: "fail_closed" | "degrade_with_warning"
    min_completed_advisors: int
    min_completed_reviews: int
    allow_same_family_fallback: bool           # donor currently DOES this (§11)
    max_retries: int
    chairman_when_required_analysis_missing: "fail_closed" | "synthesize_with_gap_note"
    on_budget_exhausted: "stop" | "degrade"
}

CouncilRunStatus = COMPLETED | DEGRADED | FAILED
StageOutcome { status: completed|failed|skipped, model?, attempts, error? }
```

- **High-stakes packs (finance):** fail-closed when mandatory Fact or Risk
  analysis is unavailable — no verified claims without a Fact Analyst, no verdict
  presented as adversarially reviewed without a Risk Reviewer, no synthesized
  verdict if the Chairman fails (return stage artifacts instead).
- **Low-stakes packs (brainstorming/dynamic):** may return `DEGRADED` with
  explicit warnings.
- Retries kept conservative (donor does none); define the policy now, implement
  minimally.

---

## 9. Reproducible run manifest & replay semantics

Every run persists a `RunManifest` (§5) — this is what makes dynamic rosters and
routed decisions debuggable and promotable. Templates must carry a
**version id or content-hash** for `prompt_template_versions` to be fillable
(concrete requirement, surfaced now, not in Phase 5).

**Replay semantics (refinement — do not oversell):** the manifest guarantees
**plan/input reproducibility** — reconstruct the exact `CouncilSpec`, prompts,
roster, repairs, seed, and assignments for audit, debugging, and promotion. It
does **not** guarantee **identical output**: LLM sampling is non-deterministic,
and the `seed` controls only *our* RNG (anonymization order, reviewer pairing),
not model generation. If a model is later deprecated, replay runs on a
**substitute with the substitution recorded** — not on the original. "Replayable"
means the plan is faithfully reconstructable, not that prose is bit-identical.

---

## 10. Pydantic boundary

Use Pydantic **only** at untrusted or persisted boundaries: `pack.yaml`, router
classifier output, `RoleDraft`, pack-defined verdict, external CLI/API input,
`RunManifest`. Keep the donor's working **dataclasses internally** (engine types
like `PersonaSpec`, `AdvisorResult`, `AgentOutcome`, and the in-memory
`CouncilResult`).

Crisp separation (refinement): the persisted `RunManifest` is a **Pydantic
projection** of a run at the persistence boundary — it does **not** turn the
in-memory `CouncilResult` into Pydantic. This keeps "Pydantic at persisted
boundaries" true without letting it creep into the live engine types.

---

## 11. Contradictions / couplings found in the donor

Surfaced from reading the full engine — these are the concrete extraction risks:

1. **Mode is hardcoded** to `("plan","review")` in `config_loader._build_personas`
   and in `prompts.py`. Must become pack-defined modes.
2. **Prompts are dev-coupled** — "Dev Council reviewing engineering work",
   "cite path:line", "use git diff", `SHIP/FIX-THEN-SHIP`. Move to pack files.
3. **Grounding is git-only** — `dispatch.py` imports `gather_repo_context`
   directly; `cwd`/`diff_scope` are threaded through dispatch/peer/chairman.
   Replace with an injected `Grounding` provider + `GroundingRequest`.
4. **Cursor-centric defaults & model validation** — `backend` defaults to
   `"cursor"` everywhere; `resolve_models` validates only cursor-backed models
   against the Cursor catalog; `_cursor_needed_for` gates model discovery on
   Cursor. A provider-only pack (finance) must cleanly skip the Cursor discovery
   path, and model availability/validation must generalize beyond the Cursor
   catalog. **This is the single largest extraction risk.**
5. **Same-family peer-review fallback** — `_pick_reviewer_model` falls back to
   `default_model` (same family as the advisor) when the pool has no
   different-family reviewer, silently degrading diversity. Surface this via
   `ExecutionPolicy.allow_same_family_fallback` + a warning, rather than silent.
6. **Chairman already separate** — not a defect; recorded so the `CouncilSpec`
   change is understood as hardening, not redesign.

---

## 12. Testing strategy (replaces "match dev-council output")

Exact live-output parity is not achievable. Use layers:

1. **Deterministic characterization** (fake backends, fixed responses, fixed
   seed): assert selected personas, rendered prompts, grounding placement,
   dispatch order, anonymization, peer-review pairing, chairman input, result
   structure, and metering calls.
2. **Prompt-rendering parity:** given the same request + repo fixture, normalize
   and diff prompts produced by the old engine vs. the new one.
3. **Grounding fixture parity:** fixed repo/document fixtures → stable bundles.
4. **Live smoke:** run both against a brief and assert invariants (same intended
   personas, all stages ran, valid output contract, no missing reviews) — never
   identical prose.

Leverage the donor's injectable `config`, RNG `seed`, and `plan_council`
dry-run to keep these cheap. **Build a characterization harness around the donor
in Phase 0, before moving any code** — that is the extraction safety net.

---

## 13. Build phases

Each phase: **deliverables · acceptance gate · regression risks · tests before
advancing.**

### Phase 0 — Characterize the donor (no code moved)
- **Deliverables:** characterization harness around `C:\dev-council` with fake
  backends; captured rendered prompts; repo-grounding fixtures; inventory of
  global/env/state and Cursor-coupling points (§11).
- **Gate:** donor behavior (persona selection, prompts, stages, metering) is
  captured as golden fixtures that run green against the untouched donor.
- **Risks:** hidden global state / env reliance in donor.
- **Tests:** the harness itself, pinned to donor output.

### Phase 1 — Define normalized contracts + pack schema (no LLM execution)
- **Deliverables:** all §5 types; `pack.yaml` schema v1; `PackDefinition`
  normalization + validation; Pydantic boundary models; `ExecutionPolicy`.
- **Gate:** a fixture `pack.yaml` loads → `PackDefinition`; invalid manifests
  fail with clear errors; no engine code references a domain name.
- **Risks:** over-engineering models before a consumer exists.
- **Tests:** pack load/validate unit tests; schema round-trip tests.

### Phase 2 — Extract engine + port Dev
- **Deliverables:** engine copied into `council_core`; prompt + grounding
  injection; Cursor discovery path made cleanly skippable; `dev` built-in pack.
- **Gate (real parity gate):** characterization + prompt-parity tests from
  Phase 0 pass against the new engine running the `dev` pack; live smoke passes.
- **Risks:** Cursor-coupling (§11.4); mode de-hardcoding regressions.
- **Tests:** characterization, prompt-parity, grounding-fixture, live smoke.

### Phase 3 — Port Finance + document grounding
- **Deliverables:** `finance` pack from retirement YAMLs; `DocumentGrounding`;
  schema-validated finance verdict; provider-only backend path exercised.
- **Gate:** `council run --pack finance` yields a schema-valid decision brief
  with correct provenance and fail-closed behavior on missing Fact/Risk.
- **Risks:** proves whether the pack abstraction is truly domain-independent;
  provider-only model validation.
- **Tests:** finance characterization; grounding provenance; ExecutionPolicy
  fail-closed tests.

### Phase 4 — Router + application-level choice UX
- **Deliverables:** deterministic trigger scoring; LLM classifier for ambiguity;
  `RouteDecision`; CLI interaction; defined non-interactive behavior.
- **Gate:** clear briefs route to the right pack; ambiguous ones return
  `choice_required`; non-interactive callers get a structured result, never a
  hang.
- **Risks:** classifier cost/latency; UX leaking into the router.
- **Tests:** routing unit tests (fixtures per pack); non-interactive path test.

### Phase 5 — Dynamic council generation + repair
- **Deliverables:** `PersonaArchitect` (`RoleDraft`), deterministic
  normalize/repair, `PersonaCompiler`, model assignment, cap enforcement, full
  generation provenance in the manifest; roster quality-state marker.
- **Gate:** a novel topic yields ≤5 valid personas incl. mandatory roles; every
  repair is recorded; a heavily repaired roster is flagged, not presented as a
  clean first-pass result; the run is plan-reproducible from its manifest.
- **Risks:** prompt injection via brief; generic/shallow SMEs; over-repair.
- **Tests:** architect output validation; repair determinism; injection tests;
  manifest replay (plan-level) test.

### Phase 6 — Career + draft-only pack promotion
- **Deliverables:** `career` pack (ported or fresh); `council pack
  draft-from-run <run-id>` and `council pack validate <path>`.
- **Gate:** career runs end-to-end; promotion produces a **draft** pack
  requiring human review — never auto-promoted into a trusted pack.
- **Risks:** career source may be missing (write fresh).
- **Tests:** career characterization; promotion draft/validate tests.

---

## 14. Open items

- **CLI name collision:** both `council-core` and the donor `dev-council-runner`
  register the `console_scripts` name `council`. In this environment the
  `council` script currently resolves to council-core while the donor is still
  reachable via `python -m council`; a reinstall could flip the script. Resolve
  before shipping — likely by uninstalling `dev-council-runner` once it is fully
  absorbed as the `dev` pack, or renaming one entry point.
- **Pydantic** adoption confirmed as boundary-only (§10) — revisit only if the
  run envelope's serialization needs push it inward.
- Decide the **user pack directory** path convention (`~/.council/packs/`).
- **Draft-only pack promotion** (`council pack draft-from-run`) — Phase 6's
  remaining feature; not yet built.
