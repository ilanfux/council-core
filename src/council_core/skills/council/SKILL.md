---
name: council
description: >-
  Convenes a multi-model council (diverse AI advisors + Chairman) via the
  `council` CLI for code review, planning, career/offer/resume decisions,
  finance/pension questions, or novel topics. Use when the user asks to convene
  a council, run a multi-model review, peer-review a change across model
  families, review a PR/plan with advisors, evaluate a job offer or resume,
  ask about keren hishtalmut/pension/tax withdrawals, or says "ask the council"
  / "council this" / "grounded cursor review". Prefers the real Python council
  when Cursor or provider API keys are ready; otherwise runs a same-model
  in-chat simulation with no setup required.
---

# Council skill

Two modes. Prefer the real CLI when it can run; otherwise simulate locally in
this chat. Never leave the user blocked on missing keys.

## Mode selection (do this first)

1. Try to run `council backends` from the repo venv if available:
   - `C:\Projects\council-core\.venv\Scripts\council.exe backends`
   - or `council backends` if on PATH
2. **If at least one backend is ready** → **Real mode** (shell out to Python).
3. **If no backends are ready, `council` is missing, or the check fails** →
   **Simulated mode** (run entirely in this chat on the current model).
4. Do **not** ask the user to set API keys before answering. Simulated mode is
   the default zero-setup path.

Optional: if the user explicitly says they want a *real multi-model* run, tell
them which key to set. Otherwise just deliver a council verdict.

## Real mode (API / Cursor key available)

Shell out to the `council` CLI. Do **not** invent advisor answers yourself.

### Pack choice

| User intent | Pack | Mode / notes |
|---|---|---|
| Code review / PR / bug hunt | `dev_cursor` when Cursor ready and repo grounding matters; else `dev` | `--mode review` |
| Design / plan / architecture | same | `--mode plan` |
| Career strategy / path | `career_cursor` only if Cursor ready and docs under `--cwd`; else `career` | `--mode strategy` |
| Resume critique | same career rule | `--mode resume` |
| Interview prep | same career rule | `--mode interview` |
| Offer decision | same career rule | `--mode offer` |
| Pension / tax / withdrawal / budget | `finance_cursor` only if Cursor ready and docs under `--cwd`; else `finance` | `--ground` docs |
| Multi-day trip / food / route | `travel` by default; `travel_cursor` if Cursor grounding wanted | modes `plan`/`food`/`route` |
| Novel topic | `--dynamic` | no pack |

Always pass `--pack` or `--dynamic` and `--non-interactive`. Prefer `--json`.

### Grounding

- `dev` / `dev_cursor`: `--cwd` = repo root.
- `finance` / `career` / `travel`: `--ground "documents=label::path"`.
- Document `*_cursor` packs: put files under `--cwd` (agents only browse cwd).

### Run

```bash
council run --pack <id> --mode <mode> --stakes standard --non-interactive --json \
  --cwd <repo> \
  --brief "<concise brief>"
```

Present stderr model map + `markdown` / `verdict.text`. Do not silently rewrite
the Chairman's conclusion. Mention `cascade_tier` and warnings.

## Simulated mode (no backends / zero setup)

This is the easy path. Stay in this chat. Role-play a small council on the
**current model**. Mark the output clearly as simulated.

### Rules

1. Read the user's materials yourself (resume, PR, docs, repo files).
2. Pick 3–5 distinct advisor personas for the topic, always including:
   - a domain specialist (or 1–2)
   - a Risk / Skeptic auditor
   - a Fact / Evidence analyst
   - a Chairman who synthesizes last
3. Write each advisor's take **separately** (short, opinionated, not identical).
4. Have the Chairman produce one decisive verdict. Do not end on "it depends."
5. Label the run up front:

```text
Mode: simulated (same chat model — not a real multi-model council)
```

6. Keep it useful and concrete. Cite file paths / evidence you actually read.
7. At the end, add one line: real multi-model diversity needs a provider key or
   `CURSOR_API_KEY`; until then this is a same-model simulation.

### Output shape

```markdown
Mode: simulated (same chat model — not a real multi-model council)

### Advisors
- <Persona 1>: ...
- <Persona 2>: ...
- <Persona 3>: ...

### Peer-style tensions
- Where they disagree (1–3 bullets)

### Chairman verdict
- Decisive recommendation
- Key risks
- One concrete next action
```

For resume / career / finance / travel / code review, adapt the chairman
sections to the domain (e.g. SHIP/FIX for review; hire-fit + rewrite notes for
resume).

## Quick reference

- Real mode when backends ready: `council packs`, `council backends`, `council models --pack dev_cursor`
- Simulated mode when nothing is ready: no install, no keys, just answer
- If `council` not found and user wants real mode later:
  `pip install -e C:\Projects\council-core` then `council skill install`
