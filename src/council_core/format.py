"""Render a CouncilResult as markdown or JSON. Presentation only — no reasoning here."""

from __future__ import annotations

import json
from typing import Any, Dict, List

from council_core.result import CouncilResult


def render_markdown(result: CouncilResult) -> str:
    parts: List[str] = []

    if not result.convened:
        parts.append("## Council not convened")
        if result.route and result.route.kind == "choice_required":
            parts.append(f"_Routing needs a choice ({result.route.reason})._")
            if result.route.candidates:
                parts.append("Candidates:")
                parts.append(
                    "\n".join(
                        f"- `{c.pack_id}` (score {c.score})" for c in result.route.candidates
                    )
                )
            parts.append("Re-run with `--pack <id>` or `--dynamic`.")
        else:
            parts.extend(result.warnings)
        return "\n\n".join(parts) + "\n"

    council = result.council
    header = (
        f"_Pack: {council.pack_id} | mode: {council.mode} | stakes: {council.stakes} | "
        f"origin: {council.origin} | status: {result.execution.status.value}_"
    )
    convened = (
        ", ".join(f"{p.title} ({p.model}@{p.backend})" for p in council.advisors) or "none"
    )
    parts.append(header + f"\n_Convened: {convened}_")
    if council.skipped:
        parts.append(f"_Skipped: {', '.join(council.skipped)}_")

    if council.origin == "dynamic":
        parts.append(f"_Dynamic roster quality: {council.roster_quality}_")
        if council.roster_repairs:
            parts.append(
                "> Roster repairs applied:\n"
                + "\n".join(f"> - {r.kind}: {r.detail}" for r in council.roster_repairs)
            )

    if result.warnings:
        parts.append(
            "> Warnings:\n" + "\n".join(f"> - {w}" for w in dict.fromkeys(result.warnings))
        )

    if result.verdict and result.verdict.ok:
        parts.append(result.verdict.text.strip())
    else:
        reason = result.verdict.error_message if result.verdict else "chairman not run"
        parts.append(f"> Chairman verdict unavailable ({reason}). Raw council inputs below.")
        parts.append(_digest(result))

    failed = [a for a in result.advisor_results if not a.outcome.ok]
    if failed:
        parts.append(
            "### Advisors that failed to respond\n"
            + "\n".join(
                f"- {a.persona.title} ({a.persona.model}): {a.outcome.error_message}"
                for a in failed
            )
        )
    return "\n\n".join(p for p in parts if p and p.strip()) + "\n"


def result_to_dict(result: CouncilResult) -> Dict[str, Any]:
    """Machine-friendly projection for skills / --json (not the full RunManifest)."""

    route = None
    if result.route is not None:
        route = {
            "kind": result.route.kind,
            "selected_pack": result.route.selected_pack,
            "confidence": result.route.confidence,
            "reason": result.route.reason,
            "candidates": [
                {"pack_id": c.pack_id, "score": c.score, "reason": c.reason}
                for c in result.route.candidates
            ],
        }

    council = None
    if result.council is not None:
        council = {
            "pack_id": result.council.pack_id,
            "origin": result.council.origin,
            "mode": result.council.mode,
            "stakes": result.council.stakes,
            "advisors": [
                {
                    "key": p.key,
                    "title": p.title,
                    "backend": p.backend,
                    "model": p.model,
                    "family": p.family,
                    "role_id": p.role_id,
                }
                for p in result.council.advisors
            ],
            "chairman": {
                "key": result.council.chairman.key,
                "title": result.council.chairman.title,
                "backend": result.council.chairman.backend,
                "model": result.council.chairman.model,
                "family": result.council.chairman.family,
            },
        }

    return {
        "run_id": result.run_id,
        "convened": result.convened,
        "cascade_tier": result.cascade_tier,
        "model_assignments": [
            {
                "role": a.role,
                "key": a.key,
                "title": a.title,
                "backend": a.backend,
                "model": a.model,
                "family": a.family,
                "note": a.note,
            }
            for a in result.model_assignments
        ],
        "route": route,
        "council": council,
        "execution": {
            "status": result.execution.status.value,
            "stages": [
                {"stage": s.stage, "status": s.status, "detail": s.detail}
                for s in result.execution.stages
            ],
        },
        "warnings": list(result.warnings),
        "contract_violations": list(result.contract_violations),
        "verdict": (
            {
                "ok": result.verdict.ok,
                "status": result.verdict.status,
                "text": result.verdict.text,
                "error_message": result.verdict.error_message,
                "actual_model": result.verdict.actual_model,
            }
            if result.verdict
            else None
        ),
        "advisor_results": [
            {
                "key": a.persona.key,
                "title": a.persona.title,
                "backend": a.persona.backend,
                "model": a.persona.model,
                "ok": a.outcome.ok,
                "status": a.outcome.status,
                "error_message": a.outcome.error_message,
                "text": a.outcome.text if a.outcome.ok else "",
            }
            for a in result.advisor_results
        ],
        "markdown": render_markdown(result),
    }


def render_json(result: CouncilResult, *, indent: int = 2) -> str:
    return json.dumps(result_to_dict(result), indent=indent, ensure_ascii=False) + "\n"


def _digest(result: CouncilResult) -> str:
    blocks: List[str] = []
    for a in result.advisor_results:
        if a.outcome.ok:
            blocks.append(
                f"#### {a.persona.title} ({a.persona.model})\n{a.outcome.text.strip()}"
            )
    usable = [p for p in result.peer_reviews if p.outcome.ok]
    if usable:
        blocks.append(
            "#### Peer reviews\n"
            + "\n\n".join(
                f"- ({p.reviewer_model}) {p.outcome.text.strip()}" for p in usable
            )
        )
    return "\n\n".join(blocks) if blocks else "(no usable advisor responses)"
