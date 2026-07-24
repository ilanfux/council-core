---
name: council
description: >-
  Convenes a multi-model council (diverse AI advisors + Chairman) via the
  `council` CLI for code review, planning, career/offer/resume decisions,
  finance/pension questions, or novel topics. Use when the user asks to convene
  a council, run a multi-model review, peer-review a change across model
  families, review a PR/plan with advisors, evaluate a job offer or resume,
  ask about keren hishtalmut/pension/tax withdrawals, or says "ask the council"
  / "council this" / "grounded cursor review". Prefers Cursor SDK multi-model
  (`dev_cursor`) when CURSOR_API_KEY is set; otherwise free provider packs.
---

# Council skill

Shell out to the `council` CLI. Do **not** invent advisor answers yourself.
The pack chooses models; you choose pack / mode / brief / grounding.

## Prerequisites

- `council` on PATH (`pip install -e .` from the council repo, or installed package).
- Credentials from environment only (never write keys to files).
- Optional: `CURSOR_API_KEY` + `pip install cursor-sdk` for grounded multi-model.
- Cascade Priority C: pass the model *you* are running as
  `--ui-model <id>` (or set `COUNCIL_UI_MODEL`) so the engine can fall back to
  you if Cursor + provider APIs are unavailable.

## When to trigger

| User intent | Pack | Mode / notes |
|---|---|---|
| Code review / PR / bug hunt | `dev_cursor` if Cursor key ready, else `dev` | `--mode review` |
| Design / plan / architecture | same | `--mode plan` |
| Career strategy / path | `career_cursor` if Cursor key ready, else `career` | `--mode strategy` |
| Resume critique | same career pack | `--mode resume` |
| Interview prep | same career pack | `--mode interview` |
| Offer decision | same career pack | `--mode offer` |
| Pension / tax / withdrawal / budget | `finance_cursor` if Cursor key ready, else `finance` | documents via `--ground` |
| Novel / uncategorizable topic | `--dynamic` | no pack |

Always pass `--pack` or `--dynamic` explicitly (skills know intent — avoid
`choice_required` round-trips). Use `--non-interactive`.

## Steps

1. **Build a brief** from the user's request (and relevant file paths / diffs).
2. **Pick pack + mode** from the table above.
3. **Grounding**
   - `dev` / `dev_cursor`: run with `--cwd` set to the repo root (git grounding).
   - `finance` / `career`: collect text docs and pass
     `--ground "documents=label::C:\path\to\file.txt"` (repeatable). PDF/docx
     must be exported to text for now.
4. **UI fallback model**: if you know your own model id, add
   `--ui-model <id>`. Prefer Cursor backend for that fallback
   (`--ui-backend cursor`) when a Cursor key exists.
5. **Run** (prefer JSON so you can parse status/warnings):

```bash
council run --pack <id> --mode <mode> --stakes standard --non-interactive --json \
  --cwd <repo> \
  --ui-model <your-model-id> \
  --brief "<concise brief>"
```

For Cursor-grounded code review:

```bash
council run --pack dev_cursor --mode review --stakes thorough --non-interactive --json \
  --cwd <repo> --brief "<what to review>"
```

6. **Before/during output**: the CLI prints a persona→model map to stderr
   *before* dispatch. Surface that map to the user briefly, then present the
   verdict. With `--json`, also read `model_assignments` and `cascade_tier`.
7. **Present** `markdown` (or `verdict.text`) to the user. Mention warnings and
   any failed advisors. Do not silently rewrite the Chairman's conclusion.

## Pack quick reference

- `council packs` — list packs
- `council backends` — which keys are ready
- `council models --pack dev_cursor` — Cursor catalog + resolution preview

## Failure handling

- Exit 2 + `route.kind == choice_required`: ask the user which pack, then re-run
  with `--pack` / `--dynamic`.
- Cursor missing: cascade falls to provider APIs, then `--ui-model`. Tell the
  user which cascade tier ran (`cascade_tier` in JSON).
- `council` not found: tell the user to `pip install -e C:\council` (or their
  clone path) and re-run `council skill install`.
