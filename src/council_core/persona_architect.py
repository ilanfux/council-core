"""Dynamic roster generation.

Pipeline:  PersonaArchitect -> RoleDrafts -> deterministic normalize/repair
           -> PersonaCompiler (trusted templates) -> model assignment.

The architect proposes *what expertise* is needed as constrained ``RoleDraft``s.
It never emits a raw system prompt and never picks models/backends/retries. A
trusted ``PersonaCompiler`` owns the final prompt structure and bounds every
architect-supplied string (see ``compile_persona``), which limits — but does not
eliminate — a hostile brief's influence. Because advisors have no tools or side
effects and only feed the Chairman, the residual risk is a lower-quality
persona, not an action taken. Generated rosters stay comparable and promotable.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

from pydantic import BaseModel, Field, ValidationError

from council_core.input import PersonaSpec
from council_core.spec import RosterRepair

# --------------------------------------------------------------------------- #
# Contract + draft schema                                                      #
# --------------------------------------------------------------------------- #

MANDATORY_ADVISOR_ROLES = ("risk_auditor", "fact_analyst")


@dataclass
class DynamicCouncilContract:
    required_advisor_roles: Tuple[str, ...] = MANDATORY_ADVISOR_ROLES
    chairman_required: bool = True
    max_total_personas: int = 5  # chairman + advisors

    @property
    def max_advisors(self) -> int:
        return self.max_total_personas - 1  # chairman is separate


class RoleDraft(BaseModel):
    role_id: str
    title: str
    objective: str = ""
    focus_areas: List[str] = Field(default_factory=list)
    questions_to_answer: List[str] = Field(default_factory=list)
    evidence_requirements: List[str] = Field(default_factory=list)
    evaluation_lens: List[str] = Field(default_factory=list)
    adversarial: bool = False


# --------------------------------------------------------------------------- #
# Trusted defaults for mandatory roles                                         #
# --------------------------------------------------------------------------- #

_TRUSTED_ROLES = {
    "risk_auditor": RoleDraft(
        role_id="risk_auditor",
        title="Risk & Irreversibility Auditor",
        objective="Independently challenge the emerging recommendation and surface what looks fine only because a fact, downside, or irreversible consequence was omitted.",
        focus_areas=["downside scenarios", "irreversibility", "missing evidence", "overconfidence"],
        questions_to_answer=["What is the strongest case AGAINST the leading option?", "Which uncertainty is material enough to block a decision?"],
        evaluation_lens=["adversarial", "uncertainty calibration"],
        adversarial=True,
    ),
    "fact_analyst": RoleDraft(
        role_id="fact_analyst",
        title="Fact & Evidence Analyst",
        objective="Build the auditable factual base: separate what is evidence-backed from general knowledge, assumptions, and unresolved questions.",
        focus_areas=["evidence ledger", "assumptions", "missing information"],
        questions_to_answer=["Which claims are supported by supplied evidence vs assumed?", "What is the smallest set of missing facts that blocks a reliable decision?"],
        evidence_requirements=["cite each supplied source", "flag every assumption"],
        evaluation_lens=["evidence discipline"],
        adversarial=False,
    ),
    "chairman": RoleDraft(
        role_id="chairman",
        title="Chairman",
        objective="Synthesize the advisors and peer reviews into one decisive, evidence-grounded verdict; surface genuine disagreement rather than manufacturing consensus.",
        evaluation_lens=["synthesis", "decisiveness"],
    ),
}


def _slug(value: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (value or "").strip().lower()).strip("_")
    return s or "specialist"


# --------------------------------------------------------------------------- #
# Architect (LLM boundary)                                                     #
# --------------------------------------------------------------------------- #

_ARCHITECT_PROMPT = """You are the roster architect for an advisory council facing a NOVEL topic.
Decide which specialist advisors are needed to reason about this brief well.

The brief:
---
{brief}
---

The council ALWAYS includes (do not list these): a Chairman, a Risk & Irreversibility
Auditor, and a Fact & Evidence Analyst. Your job is to propose {max_smes} or fewer
ADDITIONAL subject-matter expert advisors specific to this brief.

Return ONLY a JSON array (no prose) of role objects with these fields:
  role_id            (snake_case id, e.g. "distributed_systems_specialist")
  title              (human title)
  objective          (one sentence: what this advisor is responsible for)
  focus_areas        (3-6 short strings)
  questions_to_answer (2-4 short strings)
  evidence_requirements (0-3 short strings)
  evaluation_lens    (1-3 short strings)
  adversarial        (boolean; usually false for SMEs)

Propose only genuinely distinct expertise. Fewer, sharper roles beat more.
"""


class PersonaArchitect:
    """Turns a brief into constrained RoleDrafts via an injected generate fn."""

    def __init__(self, generate: Callable[[str], str]) -> None:
        self._generate = generate
        self._last_raw: Optional[str] = None

    def design(self, brief: str, contract: DynamicCouncilContract) -> Tuple[List[RoleDraft], str]:
        max_smes = contract.max_advisors - len(contract.required_advisor_roles)
        prompt = _ARCHITECT_PROMPT.format(brief=brief, max_smes=max(0, max_smes))
        raw = self._generate(prompt) or ""
        self._last_raw = raw
        drafts = _parse_drafts(raw)
        return drafts, raw


def _parse_drafts(raw: str) -> List[RoleDraft]:
    """Best-effort parse of a JSON array of role drafts from model output."""

    text = raw.strip()
    # strip code fences if present
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    # find the first JSON array
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end < start:
        return []
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []
    drafts: List[RoleDraft] = []
    for entry in data if isinstance(data, list) else []:
        if not isinstance(entry, dict):
            continue
        try:
            drafts.append(RoleDraft.model_validate(entry))
        except ValidationError:
            continue
    return drafts


# --------------------------------------------------------------------------- #
# Deterministic normalize + repair                                             #
# --------------------------------------------------------------------------- #

def normalize_and_repair(
    drafts: List[RoleDraft], contract: DynamicCouncilContract
) -> Tuple[List[RoleDraft], List[RosterRepair]]:
    """Return (advisor_drafts, repairs). Advisors exclude the chairman."""

    repairs: List[RosterRepair] = []

    # 1. normalize role ids, drop the chairman if the model emitted one
    seen = set()
    normalized: List[RoleDraft] = []
    for d in drafts:
        rid = _slug(d.role_id)
        if rid != d.role_id:
            repairs.append(RosterRepair("normalized_role_id", f"{d.role_id!r} -> {rid!r}"))
            d = d.model_copy(update={"role_id": rid})
        if rid == "chairman":
            repairs.append(RosterRepair("removed_duplicate", "architect proposed a chairman; core supplies it"))
            continue
        # 2. dedupe
        if rid in seen:
            repairs.append(RosterRepair("removed_duplicate", f"duplicate role '{rid}'"))
            continue
        seen.add(rid)
        normalized.append(d)

    # 3. inject missing mandatory advisor roles (trusted defaults)
    for role in contract.required_advisor_roles:
        if role not in seen:
            repairs.append(RosterRepair("injected_role", f"mandatory role '{role}' was missing"))
            normalized.insert(0, _TRUSTED_ROLES[role])
            seen.add(role)

    # 4. order: mandatory first, then SMEs; trim SMEs to cap
    mandatory = [d for d in normalized if d.role_id in contract.required_advisor_roles]
    smes = [d for d in normalized if d.role_id not in contract.required_advisor_roles]
    # Mandatory roles are non-negotiable; if the cap is smaller than the mandatory
    # set, SMEs are simply squeezed to zero (never a negative slice).
    max_smes = max(0, contract.max_advisors - len(mandatory))
    if len(smes) > max_smes:
        for extra in smes[max_smes:]:
            repairs.append(RosterRepair("trimmed_to_cap", f"dropped SME '{extra.role_id}' (cap {contract.max_total_personas})"))
        smes = smes[:max_smes]

    return mandatory + smes, repairs


# --------------------------------------------------------------------------- #
# Persona compiler (trusted templates -> executable PersonaSpec)               #
# --------------------------------------------------------------------------- #

@dataclass
class ModelAssignment:
    backend: str
    model: str
    family: str


_MAX_FIELD_CHARS = 400
_MAX_LIST_ITEMS = 8


def _clip(text: str) -> str:
    t = " ".join(str(text).split())  # collapse whitespace/newlines the model may inject
    return t[:_MAX_FIELD_CHARS]


def _clip_list(items: List[str]) -> List[str]:
    return [_clip(i) for i in items[:_MAX_LIST_ITEMS] if str(i).strip()]


def compile_persona(draft: RoleDraft, assignment: ModelAssignment) -> PersonaSpec:
    """Turn a RoleDraft into an executable PersonaSpec with a trusted prompt.

    The compiler owns the prompt STRUCTURE and role: architect-supplied strings
    are bounded (length + item count) and whitespace-collapsed so they read as
    role description, not as free-form instruction blocks. This limits — it does
    not eliminate — a hostile brief's influence; advisors have no tools/side
    effects and their output only feeds the Chairman, so the residual risk is a
    lower-quality persona, not an action taken.
    """

    lines: List[str] = [f"You are the {_clip(draft.title)} on an advisory council."]
    if draft.objective:
        lines.append(f"\nYour objective: {_clip(draft.objective)}")
    focus = _clip_list(draft.focus_areas)
    if focus:
        lines.append("Focus on: " + "; ".join(focus) + ".")
    questions = _clip_list(draft.questions_to_answer)
    if questions:
        lines.append("Answer specifically: " + " ".join(f"({i+1}) {q}" for i, q in enumerate(questions)))
    evidence = _clip_list(draft.evidence_requirements)
    if evidence:
        lines.append("Evidence rules: " + "; ".join(evidence) + ".")
    if draft.adversarial:
        lines.append("Be adversarial: do not optimize for agreement; hunt the weakness.")
    prompt = "\n".join(lines).strip()

    return PersonaSpec(
        key=draft.role_id,
        title=draft.title,
        prompt=prompt,
        model=assignment.model,
        family=assignment.family,
        capability="heavy" if draft.adversarial else "medium",
        core=draft.role_id in MANDATORY_ADVISOR_ROLES,
        triggers=[],
        backend=assignment.backend,
        role_id=draft.role_id if draft.role_id in MANDATORY_ADVISOR_ROLES else None,
    )


def assign_models(
    n: int, available: List[ModelAssignment], chairman_family: Optional[str] = None
) -> List[ModelAssignment]:
    """Spread ``n`` assignments across families for de-correlated blind spots.

    Prefers a different family than the chairman for the first advisor (the Risk
    Auditor). Falls back gracefully when only one family is available.
    """

    if not available:
        raise ValueError("no available model assignments for dynamic council")

    families: dict = {}
    for a in available:
        families.setdefault(a.family, a)
    ordered = list(families.values())
    if chairman_family and len(ordered) > 1:
        ordered.sort(key=lambda a: a.family == chairman_family)  # non-chairman families first

    out: List[ModelAssignment] = []
    i = 0
    while len(out) < n:
        out.append(ordered[i % len(ordered)])
        i += 1
    return out
