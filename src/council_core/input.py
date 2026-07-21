"""Core input/result contracts (in-memory, dataclasses).

Generalized from the dev-council donor: ``PersonaSpec.lens`` becomes the more
neutral ``prompt`` (a persona's system prompt), a ``role_id`` tags mandatory
roles, and the run request is domain-neutral (no ``mode``/``diff_scope`` baked
in — those come from the pack / grounding request).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional


@dataclass
class PersonaSpec:
    """A single advisor lens and the model it runs on."""

    key: str
    title: str
    prompt: str
    model: str
    family: str
    capability: str = "medium"
    core: bool = False
    triggers: List[str] = field(default_factory=list)
    # Family-specific model parameters, e.g. {"reasoning": "high"} (GPT/Codex) or
    # {"thinking": "true", "effort": "high"} (Claude). Empty = provider default.
    model_params: Dict[str, str] = field(default_factory=dict)
    # Execution backend key (resolved against the runtime backend registry). The
    # default is supplied by the pack, never hardcoded to a specific provider.
    backend: str = "cursor"
    # Mandatory-role tag: "chairman" | "risk_auditor" | "fact_analyst" | None.
    # Used by the execution policy and the dynamic core contract.
    role_id: Optional[str] = None


@dataclass
class CouncilRequest:
    """Everything needed to run one council, before routing/roster selection."""

    brief: str
    cwd: str = "."
    mode: Optional[str] = None            # pack-defined mode (or None -> pack default)
    stakes: str = "standard"
    pack: Optional[str] = None            # explicit pack id override
    pack_path: Optional[str] = None       # explicit external pack path override
    dynamic: bool = False                 # force a dynamic council
    roster: Optional[List[str]] = None    # explicit advisor keys (pack rosters only)
    peer_review_override: Optional[bool] = None
    grounding_args: Mapping[str, str] = field(default_factory=dict)


@dataclass
class AgentOutcome:
    """Normalized result of a single backend agent run."""

    status: str  # "finished" | "error" | "startup_error"
    text: str
    run_id: Optional[str] = None
    agent_id: Optional[str] = None
    error_message: Optional[str] = None
    duration_ms: Optional[int] = None
    actual_model: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.status == "finished" and bool(self.text.strip())


@dataclass
class AdvisorResult:
    """One advisor's contribution."""

    persona: PersonaSpec
    outcome: AgentOutcome


@dataclass
class PeerReviewResult:
    """One peer review of the anonymized advisor set."""

    reviewer_for_key: str
    reviewer_model: str
    reviewer_family: str
    outcome: AgentOutcome
