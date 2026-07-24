"""Optional LLM classifier for ambiguous routing (Pydantic at the boundary)."""

from __future__ import annotations

import json
import re
from typing import Callable, List, Optional, Set

from pydantic import BaseModel, Field, ValidationError

from council_core.router import RouteCandidate, RouteDecision


class ClassifierOutput(BaseModel):
    """What the LLM classifier may emit — validated before trust."""

    kind: str = Field(description="pack | dynamic | choice_required")
    selected_pack: Optional[str] = None
    reason: str = ""
    confidence: float = 0.0


_CLASSIFIER_PROMPT = """You route a user brief to a council pack.

Allowed packs: {pack_ids}
Also allowed kinds: "dynamic" (novel topic) or "choice_required" (still ambiguous).

Brief:
---
{brief}
---

Candidates already scored (pack_id:score): {candidates}

Reply with ONLY compact JSON, no markdown:
{{"kind":"pack"|"dynamic"|"choice_required","selected_pack":"<id or null>","reason":"<short>","confidence":0.0-1.0}}
"""


def _extract_json(text: str) -> dict:
    text = (text or "").strip()
    if not text:
        raise ValueError("empty classifier response")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def classify_route(
    brief: str,
    candidates: List[RouteCandidate],
    pack_ids: Set[str],
    generate: Callable[[str], str],
) -> Optional[RouteDecision]:
    """Ask the LLM classifier. Returns None if generation/validation fails."""

    prompt = _CLASSIFIER_PROMPT.format(
        pack_ids=", ".join(sorted(pack_ids)) or "(none)",
        brief=brief.strip(),
        candidates=", ".join(f"{c.pack_id}:{c.score}" for c in candidates) or "(none)",
    )
    try:
        raw = generate(prompt)
        data = _extract_json(raw)
        out = ClassifierOutput.model_validate(data)
    except (ValueError, ValidationError, TypeError, json.JSONDecodeError):
        return None

    kind = (out.kind or "").strip().lower()
    if kind not in {"pack", "dynamic", "choice_required"}:
        return None

    selected = out.selected_pack
    if kind == "pack":
        if not selected or selected not in pack_ids:
            return None
        return RouteDecision(
            kind="pack",
            selected_pack=selected,
            candidates=list(candidates),
            confidence=max(0.0, min(1.0, float(out.confidence or 0.0))),
            reason=out.reason or f"LLM classifier selected '{selected}'",
        )
    if kind == "dynamic":
        return RouteDecision(
            kind="dynamic",
            candidates=list(candidates),
            confidence=max(0.0, min(1.0, float(out.confidence or 0.0))),
            reason=out.reason or "LLM classifier chose dynamic",
        )
    return RouteDecision(
        kind="choice_required",
        candidates=list(candidates),
        confidence=max(0.0, min(1.0, float(out.confidence or 0.0))),
        reason=out.reason or "LLM classifier still ambiguous",
    )
