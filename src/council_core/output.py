"""Output contracts.

A pack declares how its Chairman verdict is shaped — either a named built-in
contract (``output.schema: dev_verdict_v1``) or a declarative contract file
(``output.schema_file: output_contract.yaml``). We do NOT impose one universal
verdict schema across domains; we DO require every verdict be schema-validated
(never an arbitrary blob).

v1 validation is declarative and section-based: a contract supplies a markdown
skeleton the Chairman must follow and a list of required section markers we check
the produced verdict for. This is intentionally lighter than parsing free-form
prose into typed fields, while still rejecting a verdict that ignored the
contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple

import yaml


@dataclass
class OutputContract:
    schema_id: str
    skeleton: str
    required_sections: Tuple[str, ...] = ()

    def validate(self, verdict_text: str) -> List[str]:
        """Return a list of contract violations (empty == valid)."""

        text = (verdict_text or "").lower()
        missing = [s for s in self.required_sections if s.lower() not in text]
        if missing:
            return [f"verdict missing required section marker: '{s}'" for s in missing]
        return []


_GENERIC_SKELETON = """## Council Verdict: <topic>

### Conclusion
<the decisive recommendation — not "it depends">

### Key findings
<the high-signal points advisors converged on>

### Risks
<material risks and irreversible actions>

### Where the council disagreed
<genuine disagreements, both sides>

### Next actions
<concrete next steps>

### Limitations
<what remains unverified or out of scope>"""

_DEV_REVIEW_SKELETON = """## Council Verdict (Review): <what changed>
_Convened: <reviewers> — skipped: <specialists + why>_

### Must fix before merge (blocking)
- <finding> — `path:line` — why it matters

### Should fix (non-blocking)
- <finding> — `path:line`

### Where reviewers disagreed
<the call, with reasoning>

### What everyone missed
<surfaced in peer review>

### Verdict
<SHIP | FIX-THEN-SHIP | RETHINK> — one-line justification"""

_DEV_PLAN_SKELETON = """## Council Verdict (Plan): <topic>
_Convened: <advisors> — skipped: <specialists + why>_

### Where the council agrees
<high-confidence points multiple advisors converged on>

### Where the council clashes
<genuine disagreements — both sides + why each is reasonable>

### Blind spots the council caught
<things that surfaced only in peer review>

### The recommendation
<a clear, decisive call>

### The one thing to do first
<a single concrete next step>"""

_FINANCE_SKELETON = """## Decision Brief: <topic>

### Decision summary
<the recommended action in one paragraph>

### Recommended action
<what to do, concretely>

### Viable alternatives
<genuine alternatives and the trade-offs>

### Cash-flow impact
<near-term liquidity effect>

### Tax / pension / insurance / employment impact
<domain effects; label each rule with jurisdiction + as_of_date>

### Evidence and assumptions
<verified_fact / sourced_rule / calculation / assumption / professional_question>

### Documents, forms, deadlines
<what is needed and by when>

### Risks and irreversibility
<Risk Auditor stop/proceed assessment>

### Professional escalation
<when to consult a licensed CPA / pension pro / employment lawyer>

### One concrete next action
<the single next step>"""

_BUILTINS = {
    "generic_verdict_v1": OutputContract(
        schema_id="generic_verdict_v1",
        skeleton=_GENERIC_SKELETON,
        required_sections=("Conclusion", "Risks", "Next actions"),
    ),
    "dev_review_v1": OutputContract(
        schema_id="dev_review_v1",
        skeleton=_DEV_REVIEW_SKELETON,
        required_sections=("Must fix before merge", "Verdict"),
    ),
    "dev_plan_v1": OutputContract(
        schema_id="dev_plan_v1",
        skeleton=_DEV_PLAN_SKELETON,
        required_sections=("The recommendation", "The one thing to do first"),
    ),
    "finance_brief_v1": OutputContract(
        schema_id="finance_brief_v1",
        skeleton=_FINANCE_SKELETON,
        required_sections=("Recommended action", "Risks and irreversibility", "One concrete next action"),
    ),
}


def builtin_contract(schema_id: str) -> OutputContract:
    if schema_id not in _BUILTINS:
        raise ValueError(
            f"Unknown output schema '{schema_id}'. Known: {', '.join(sorted(_BUILTINS))}."
        )
    return _BUILTINS[schema_id]


def load_contract_file(path: Path) -> OutputContract:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return OutputContract(
        schema_id=str(data.get("schema_id", path.stem)),
        skeleton=str(data.get("skeleton", _GENERIC_SKELETON)),
        required_sections=tuple(str(s) for s in (data.get("required_sections") or [])),
    )
