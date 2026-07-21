"""Routing: classify a brief to a predefined pack or a dynamic council.

The router NEVER performs UX. It returns a structured ``RouteDecision``; the CLI
(or an API/adapter) decides how to resolve ``choice_required`` — interactively for
a human, or as a structured error for non-interactive callers.

Stage 1 is cheap deterministic trigger scoring. An optional LLM classifier can
be injected for ambiguous cases; absent one, ambiguity resolves to
``choice_required`` so we never silently guess.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from council_core.input import CouncilRequest
from council_core.pack import PackDefinition

_MIN_ABS_SCORE = 1        # need at least one trigger hit to claim a pack
_MIN_MARGIN = 2           # winner must beat runner-up by this many hits to be confident


@dataclass
class RouteCandidate:
    pack_id: str
    score: int
    reason: str


@dataclass
class RouteDecision:
    kind: str                       # "pack" | "dynamic" | "choice_required"
    selected_pack: Optional[str] = None
    confidence: float = 0.0
    candidates: List[RouteCandidate] = field(default_factory=list)
    reason: str = ""


def _score_pack(brief_lc: str, pack: PackDefinition) -> int:
    return sum(1 for t in pack.triggers if t and t in brief_lc)


class Router:
    def __init__(self, generate: Optional[Callable[[str], str]] = None) -> None:
        self._generate = generate  # optional LLM classifier (unused in v1 default)

    def route(self, request: CouncilRequest, packs: Dict[str, PackDefinition]) -> RouteDecision:
        # explicit overrides win, no scoring
        if request.dynamic:
            return RouteDecision(kind="dynamic", reason="forced by --dynamic", confidence=1.0)
        if request.pack or request.pack_path:
            pid = request.pack or "(pack-path)"
            return RouteDecision(kind="pack", selected_pack=request.pack, confidence=1.0,
                                 reason="forced by --pack/--pack-path")

        brief_lc = (request.brief or "").lower()
        scored = sorted(
            (RouteCandidate(pid, _score_pack(brief_lc, p), "trigger match") for pid, p in packs.items()),
            key=lambda c: -c.score,
        )
        total = sum(c.score for c in scored) or 1
        top = scored[0] if scored else None
        second = scored[1] if len(scored) > 1 else None

        if not top or top.score < _MIN_ABS_SCORE:
            return RouteDecision(
                kind="choice_required",
                candidates=scored,
                confidence=0.0,
                reason="no pack triggers matched the brief",
            )

        second_score = second.score if second else 0
        margin = top.score - second_score
        confidence = top.score / total
        # Confident when there is no real competitor, or the winner clears the
        # margin over a competing pack.
        if second_score == 0 or margin >= _MIN_MARGIN:
            return RouteDecision(
                kind="pack",
                selected_pack=top.pack_id,
                candidates=scored,
                confidence=confidence,
                reason=f"'{top.pack_id}' matched {top.score} triggers (margin {margin})",
            )

        # ambiguous: two packs close together -> let the caller choose
        return RouteDecision(
            kind="choice_required",
            candidates=scored,
            confidence=confidence,
            reason=f"ambiguous: '{top.pack_id}' ({top.score}) vs "
                   f"'{second.pack_id if second else '-'}' ({second.score if second else 0})",
        )
