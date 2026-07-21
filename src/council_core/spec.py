"""CouncilSpec: the fully-resolved plan for one council run.

The Chairman is a distinct field, NOT a member of ``advisors`` — only advisors
are dispatched and peer-reviewed; the Chairman receives their completed
artifacts. This formalizes a separation the donor engine already enforced.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from council_core.grounding import Grounding
from council_core.input import PersonaSpec
from council_core.output import OutputContract
from council_core.policy import ExecutionPolicy
from council_core.prompts import PromptSet


@dataclass
class RosterRepair:
    """One deterministic repair applied to a generated roster (dynamic only)."""

    kind: str      # "injected_role" | "removed_duplicate" | "trimmed_to_cap" | "normalized_role_id"
    detail: str


@dataclass
class CouncilSpec:
    origin: str                      # "pack" | "dynamic"
    pack_id: str
    mode: str
    stakes: str
    advisors: List[PersonaSpec]      # dispatched + peer-reviewed
    chairman: PersonaSpec            # separate pipeline role
    prompt_set: PromptSet
    grounding: Grounding
    output_contract: OutputContract
    execution_policy: ExecutionPolicy
    peer_review: bool
    default_model: str
    peer_review_pool: Dict[str, str] = field(default_factory=dict)
    peer_review_backend: str = "cursor"
    peer_review_backends: Dict[str, str] = field(default_factory=dict)
    skipped: List[str] = field(default_factory=list)
    roster_repairs: List[RosterRepair] = field(default_factory=list)
    roster_quality: str = "curated"  # "curated" | "clean_generation" | "repaired"

    def advisor_role_ids(self) -> set:
        return {p.role_id for p in self.advisors if p.role_id}
