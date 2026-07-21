"""Null grounding: no external evidence.

Used by dynamic councils (v1) and any pack that reasons purely from the brief.
It is explicit about the absence of evidence so downstream personas — especially
the Fact Analyst — must distinguish evidence-backed claims from model knowledge,
assumptions, and unresolved facts.
"""

from __future__ import annotations

from council_core.grounding.bundle import GroundingBundle, GroundingRequest


class NullGrounding:
    name = "null"

    def gather(self, request: GroundingRequest) -> GroundingBundle:
        return GroundingBundle(
            items=(),
            warnings=("No external evidence source was configured for this council.",),
            token_estimate=0,
            truncated=False,
        )
