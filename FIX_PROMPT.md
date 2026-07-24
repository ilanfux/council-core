# Fix prompt — Council Core review follow-ups

> Paste below the line into Cursor. Work in `C:\council`. These are targeted
> fixes from a review of commit `f4f6c52`. **Fix exactly these; do not
> re-architect.** Keep the existing 73 tests green, add the new tests noted, and
> **commit each numbered item separately** (the last round put everything in one
> commit, which we don't want again).

---

Global constraints:
- `python -m pytest -q` must stay green (73+), all offline/fake-backend. Add the
  tests requested below.
- Respect the invariants in `PLAN.md` / `HANDOFF.md §6` (Chairman separate from
  advisors; router does no UX; Pydantic only at boundaries; credentials from env
  only; a new domain must not require editing the engine core).
- One commit per numbered fix, with a clear message.

### Fix 1 — Make the Cursor→provider downgrade LOUD and optional (highest priority)

**Problem:** `model_resolve.resolve_council_models` silently cascades a
Cursor-backed pack onto free providers when `CURSOR_API_KEY` is missing/unusable.
Running `--pack dev_cursor` with no Cursor key therefore quietly loses the
grounded repo-reading that is the whole point of the Cursor packs, with only a
buried warning.

**Fix:**
- Add a `strict_backend: bool = False` field to `CouncilRequest`
  (`input.py`) and a `--require-cursor` / `--strict` CLI flag (`cli.py`).
- In `resolve_council_models`, when `cursor_needed_for(council)` is true AND
  Priority A (Cursor) does not succeed:
  - if `strict` → return a `ResolutionResult` that signals failure (new
    `tier="failed"`), and have `orchestrator.run_council` turn that into a
    non-convened `CouncilResult` with a clear message ("this pack needs Cursor;
    set CURSOR_API_KEY or drop --require-cursor to allow provider fallback").
    Do NOT dispatch.
  - else (default) keep the cascade, but surface the downgrade **prominently**:
    prepend a one-line banner to the rendered verdict header in `format.py`
    (e.g. `> ⚠ Cursor unavailable — ran on providers (grounding lost)`) whenever
    `result.cascade_tier` is `providers` or `ui`, not only in the warnings list.

**Tests:** cascade-tier `providers` with `strict=True` → non-convened + message,
no dispatch; `strict=False` → runs + banner present. Fake the discover fn.

**Acceptance:** `dev_cursor` with no key + `--require-cursor` fails clearly;
without the flag it runs on providers with a visible banner.

### Fix 2 — Priority-C UI fallback must not default to the dead `cursor` backend

**Problem:** `model_resolve._resolve_ui_model` defaults `ui_backend` to
`"cursor"`. Priority C only runs *because Cursor already failed*, so forcing
every persona back onto `cursor` makes them all fail.

**Fix:** In the Priority-C path, never resolve `ui_backend` to `cursor`. If no
explicit `ui_backend`/`COUNCIL_UI_BACKEND` is given, pick the first ready
provider backend from `available_assignments(...)`; if none, skip Priority C and
fall through to the existing "cascade exhausted" branch. Keep `cursor` allowed
only when explicitly requested.

**Tests:** Cursor discovery fails + provider pool empty + only `COUNCIL_UI_MODEL`
set (no backend) → Priority C does not route to `cursor`; either uses a ready
provider or reports cascade-exhausted. Add to `tests/test_model_resolve.py`.

### Fix 3 — De-duplicate `SKILL.md` (single source of truth)

**Problem:** Four identical `SKILL.md` copies exist: `.claude/skills/council/`,
`.cursor/skills/council/`, `skills/council/`, `src/council_core/skills/council/`.
They will drift.

**Fix:** Keep ONE canonical source: `src/council_core/skills/council/SKILL.md`
(shipped via package-data). Delete the committed `.claude/skills/...`,
`.cursor/skills/...`, and top-level `skills/...` copies. Make
`skill_install.py` (and its `council skill install` CLI command) copy the
canonical file into the user's `~/.claude/skills/council/` and
`~/.cursor/skills/council/` on demand. Update any docs/paths that referenced the
deleted copies.

**Tests:** `skill_install` copies from the packaged source to a temp target dir
(use `tmp_path`); assert the copied file matches the source.

**Acceptance:** exactly one `SKILL.md` tracked in git under `src/council_core/`;
install command reproduces it into the host skill dirs.

### Fix 4 — Router LLM classifier OFF by default

**Problem:** The LLM classifier now fires on every ambiguous brief, adding an
unrequested model call + latency. It was scoped as optional.

**Fix:** Add `router: { use_classifier: false }` to the runtime config
(`defaults/backends.yaml` + `RuntimeConfig`) and only build/pass the classifier
`generate` fn in `orchestrator.run_council` when that flag is true. Default off:
deterministic scoring → `choice_required` on ambiguity (unchanged behavior).

**Tests:** with `use_classifier=false` an ambiguous brief returns
`choice_required` and makes no generate call (assert the fake generate is never
invoked); with `true` the classifier is consulted.

### Fix 5 — Live Cursor smoke verification (manual, then document)

**Problem:** The Cursor SDK path is only tested with mocks; never exercised
against the real beta SDK.

**Fix:** Do NOT add this to the default suite. Instead:
- Add an integration-marked test (`@pytest.mark.integration`) that runs a
  minimal `dev_cursor` review and is skipped unless `CURSOR_API_KEY` is set and
  `--run-integration` is passed.
- Then actually run it once manually and paste the result (did advisors complete
  on ≥2 model families? did they cite real `path:line`? did the Chairman
  produce a verdict?). Also confirm `council run --pack finance` still works with
  NO Cursor key.
- Record the outcome in `HANDOFF.md` (a short "Cursor verified on <date>" note).

**Acceptance:** integration test exists and is skipped by default; manual live
run result reported; provider-only packs confirmed unaffected.

---

When done, report per-fix: what changed, the new tests, and the final
`pytest -q` count. Flag anything in these instructions that conflicts with the
code as you find it rather than guessing.
