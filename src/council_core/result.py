"""CouncilResult: the typed in-memory envelope for one run (dataclasses).

The persisted, serialized form is ``RunManifest`` (Pydantic) — a projection of
this at the persistence boundary. Keeping the live result as dataclasses stops
Pydantic creeping into the engine's internal types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from council_core.grounding import GroundingBundle
from council_core.input import AdvisorResult, AgentOutcome, PeerReviewResult
from council_core.model_resolve import PersonaAssignment
from council_core.policy import RunStatus
from council_core.router import RouteDecision
from council_core.spec import CouncilSpec


@dataclass
class StageOutcome:
    stage: str                       # "grounding" | "dispatch" | "peer_review" | "chairman"
    status: str                      # "completed" | "failed" | "skipped"
    detail: str = ""
    attempts: int = 1


@dataclass
class ExecutionSummary:
    status: RunStatus
    stages: List[StageOutcome] = field(default_factory=list)


@dataclass
class CouncilResult:
    convened: bool
    route: Optional[RouteDecision]
    council: Optional[CouncilSpec]
    grounding: Optional[GroundingBundle]
    advisor_results: List[AdvisorResult]
    peer_reviews: List[PeerReviewResult]
    verdict: Optional[AgentOutcome]
    execution: ExecutionSummary
    warnings: List[str] = field(default_factory=list)
    contract_violations: List[str] = field(default_factory=list)
    run_id: str = ""
    model_assignments: List[PersonaAssignment] = field(default_factory=list)
    cascade_tier: str = ""
