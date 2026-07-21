# Council Core

One generic multi-model **council** engine. A council convenes several persona
agents — each grounded and run on a different model family — dispatches your
brief to all of them, anonymizes and peer-reviews their answers, and has a
Chairman synthesize a decisive verdict.

The engine is domain-neutral. Everything domain-specific lives in a **pack**:
the personas, their prompts, the grounding source, and the output contract.

- **Predefined packs** — curated rosters for known domains (`dev`, `career`,
  `finance`).
- **Dynamic councils** — for a novel topic, a `PersonaArchitect` designs a
  roster on the fly (capped at 5 personas, always including a Chairman, a Risk
  auditor, and a Fact analyst).

Status: **scaffolding (Phase 0).** See [PLAN.md](PLAN.md) for the architecture,
decisions, and build order.

## Layout

- `src/council_core/` — the engine.
- `packs/` — domain packs (`dev`, `career`, `finance`).
- `tests/` — test suite.

The engine is derived from the `dev-council` runner and generalized; the
`finance` pack is derived from the `retirement_council` configuration.
