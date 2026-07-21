"""Execution / degraded-mode policy.

Mandatory roles (Fact Analyst, Risk Auditor, Chairman) create failure semantics
the donor never had: it could tolerate any single advisor failing because no role
was structurally essential. Packs declare an ``ExecutionPolicy`` so high-stakes
domains fail closed while low-stakes ones degrade with a warning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Set


class RunStatus(str, Enum):
    COMPLETED = "completed"
    DEGRADED = "degraded"
    FAILED = "failed"


class MissingRoleBehavior(str, Enum):
    FAIL_CLOSED = "fail_closed"
    DEGRADE_WITH_WARNING = "degrade_with_warning"


@dataclass
class ExecutionPolicy:
    required_successful_roles: Set[str] = field(default_factory=set)
    on_missing_required_role: MissingRoleBehavior = MissingRoleBehavior.DEGRADE_WITH_WARNING
    min_completed_advisors: int = 1
    min_completed_reviews: int = 0
    allow_same_family_fallback: bool = True
    max_retries: int = 0
    chairman_when_required_analysis_missing: str = "synthesize_with_gap_note"  # or "fail_closed"
    on_budget_exhausted: str = "degrade"  # or "stop"

    @classmethod
    def from_dict(cls, data: Dict) -> "ExecutionPolicy":
        data = data or {}

        def _int(key: str, default: int) -> int:
            try:
                return int(data.get(key, default))
            except (TypeError, ValueError):
                return default

        try:
            behavior = MissingRoleBehavior(str(data.get("on_missing_required_role", "degrade_with_warning")))
        except ValueError:
            behavior = MissingRoleBehavior.DEGRADE_WITH_WARNING

        return cls(
            required_successful_roles={str(r).strip() for r in data.get("required_successful_roles", []) if r},
            on_missing_required_role=behavior,
            min_completed_advisors=_int("min_completed_advisors", 1),
            min_completed_reviews=_int("min_completed_reviews", 0),
            allow_same_family_fallback=bool(data.get("allow_same_family_fallback", True)),
            max_retries=_int("max_retries", 0),
            chairman_when_required_analysis_missing=str(
                data.get("chairman_when_required_analysis_missing", "synthesize_with_gap_note")
            ),
            on_budget_exhausted=str(data.get("on_budget_exhausted", "degrade")),
        )
