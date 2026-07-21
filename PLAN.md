# Council Core — Consolidation Plan

One generic multi-model "council" engine. A council convenes several persona
agents (each on a different model family), dispatches the brief to all of them,
anonymizes and peer-reviews their responses, and has a Chairman synthesize a
decisive verdict. The **only** things that vary by domain are the personas,
their prompts, the grounding source, and the output contract — all packaged as
a **pack**.

Two ways a roster is chosen:
- **Predefined pack** — a known domain (dev / career / finance) with a curated,
  optimized roster.
- **Dynamic council** — a novel topic where a `PersonaArchitect` meta-agent
  designs a roster on the fly.

## Provenance

- **Engine donor:** `C:\dev-council` — the cleanest, most complete existing
  runner. Copied here and de-coupled from its dev-only assumptions. Left
  untouched at its source; used as a parity reference in Phase 1.
- **Finance pack:** the six YAMLs in `C:\retirement_council` become
  `packs/finance/`. Left untouched at source.
- **Career pack:** an older, simpler Career Council that worked exactly like
  Dev Council. **Location unconfirmed** — if not found, career is written fresh
  in Phase 5.
- **Not merged:** `C:\Second_Brain_Career_Council` (LangGraph + Neo4j +
  ingestion + MCP) is a different, stateful architecture and stays separate. It
  may later consume this core as a library.

## Key decisions (locked)

1. **Router confidence UX** — on low confidence the router does not guess; it
   asks the user to choose a pack or a dynamic council. A `--pack` / `--dynamic`
   override skips the prompt.
2. **Dynamic council cap = 5 personas** — the core contract mandates 3 roles
   (Chairman, Risk auditor, Fact analyst), leaving room for 1–2 subject-matter
   experts. Beyond 5 bloats the Chairman's context and adds redundant noise.
3. **Fresh rewrite** — new repo `C:\council` (package `council_core`); existing
   projects are copied from, never overridden.

## Target layout

```
C:\council\
  pyproject.toml
  src/council_core/
    __init__.py  __main__.py  cli.py
    orchestrator.py         # was runner.py — adds Router + Roster stages
    input.py                # PersonaSpec / CouncilInput — generalized
    config_loader.py        # pack-aware, mode-agnostic
    dispatch.py             # grounding + prompts INJECTED, not imported
    peer_review.py  chairman.py  metering.py  format.py  env.py
    sdk_client.py           # cursor-specific, optional
    backends/               # copied verbatim from dev-council
    # NEW:
    router.py               # Router: brief -> pack | dynamic | ask
    roster.py               # RosterProvider + PackRoster + DynamicRoster
    persona_architect.py    # PersonaArchitect meta-agent
    profile.py              # Pack loader + core-contract validation
    grounding.py            # Grounding interface + adapters
    prompts/                # base templates as files
  packs/
    dev/      personas.yaml  prompts/  modes.yaml          (grounding: git_repo)
    career/   personas.yaml  prompts/  modes.yaml          (grounding: documents)
    finance/  personas.yaml  routing.yaml  tiers.yaml
              output_contract.yaml  model_routing.yaml  onboarding.yaml
                                                           (grounding: documents)
  tests/
```

## What moves / changes / is new (from dev-council)

| Module | Disposition | Note |
|---|---|---|
| `backends/*` | copy as-is | already domain-agnostic |
| `metering.py`, `env.py`, `sdk_client.py` | copy as-is | no dev coupling |
| `format.py` | copy, minor | pack-defined output sections |
| `peer_review.py` | light | peer-review prompt becomes injected |
| `chairman.py` | light | prompt injected; `cwd` -> generic grounding ctx |
| `dispatch.py` | medium | inject `Grounding` + `PromptSet`; `diff_scope` -> `grounding_args` |
| `config_loader.py` | medium | drop hardcoded `("plan","review")`; load pack by name; unify `lens`\|`system_prompt` -> `prompt` |
| `input.py` | medium | `PersonaSpec.lens` -> `prompt`; backend default from pack; `mode` pack-defined |
| `runner.py` -> `orchestrator.py` | rewrite front | insert Router -> RosterProvider; downstream unchanged |
| `prompts.py` | -> files | base + per-pack override under `prompts/` |
| `context.py` | -> adapter | `grounding/git_repo.py` |
| — | NEW | `router.py`, `roster.py`, `persona_architect.py`, `profile.py`, `grounding.py` |

The `dispatch -> peer_review -> chairman` core is ~unchanged. All de-coupling is
at two seams: **prompts** (hardcoded -> pack files) and **grounding** (git-only
-> pluggable). Everything new bolts onto the front.

## New interfaces (contracts)

```
# Router
RouteDecision { kind: "pack"|"dynamic"|"ask", pack: str|None,
                confidence: float, candidates: list[str] }
Router.route(brief, override) -> RouteDecision

# RosterProvider — two sources of the same list[PersonaSpec]
PackRoster.build(...)    -> wraps existing select_personas()
DynamicRoster.build(...) -> PersonaArchitect + core-contract + cap enforcement

# PersonaArchitect
CoreContract { required_roles=["chairman","risk_auditor","fact_analyst"],
               max_personas=5 }
PersonaArchitect.design(brief, contract) -> list[PersonaSpec]
# validate roles present + count<=5, then assign cross-family models via the
# diversity policy (model_routing.yaml)

# Grounding — pack-selected
Grounding.gather(brief, args) -> str
# GitRepoGrounding (dev) | DocumentGrounding (finance/career) | NullGrounding (dynamic v1)
```

## Build order (each phase independently verifiable)

0. **Scaffold** — repo skeleton, pyproject, empty packs, this plan. *(current)*
1. **Engine parity** — copy engine, de-couple the two seams, port dev pack.
   *Gate: new tool's dev output matches old dev-council.*
2. **Pack abstraction + finance** — `profile.py` + finance pack from retirement
   YAMLs. *Gate: `council run --pack finance` yields a decision brief.*
3. **Router + ask UX** — trigger match -> classifier -> ask-the-user prompt.
4. **Dynamic council** — `PersonaArchitect` + `DynamicRoster` + core-contract /
   cap-5. *Gate: a novel topic spins up <=5 valid personas.*
5. **Career pack + promotion loop** — port/write career roster; add "save this
   dynamic roster as a pack."

## Open items

- Confirm location of the older simple Career Council, or write it fresh (Ph 5).
