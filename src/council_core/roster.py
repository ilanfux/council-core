"""Roster providers: two sources of the same CouncilSpec.

``build_pack_council`` selects a curated roster from a PackDefinition (mode +
tier). ``build_dynamic_council`` generates one via the PersonaArchitect. Both
return a CouncilSpec; everything downstream (dispatch -> peer review -> chairman)
is identical.
"""

from __future__ import annotations

from typing import List, Optional

from council_core.grounding import NullGrounding
from council_core.input import CouncilRequest, PersonaSpec
from council_core.output import builtin_contract
from council_core.pack import PackDefinition
from council_core.persona_architect import (
    DynamicCouncilContract,
    ModelAssignment,
    PersonaArchitect,
    assign_models,
    compile_persona,
    normalize_and_repair,
)
from council_core.policy import ExecutionPolicy, MissingRoleBehavior
from council_core.prompts import PromptSet
from council_core.spec import CouncilSpec


def build_pack_council(pack: PackDefinition, request: CouncilRequest) -> CouncilSpec:
    mode = request.mode or pack.default_mode
    if mode not in pack.modes:
        raise ValueError(f"pack '{pack.id}' has no mode '{mode}'; known: {pack.modes}")
    tier = pack.get_tier(request.stakes)

    candidates = pack.personas_for_mode(mode)
    if not tier.convene:
        advisors: List[PersonaSpec] = []
    elif request.roster:
        unknown = [k for k in request.roster if k not in candidates]
        if unknown:
            raise ValueError(f"unknown personas for mode {mode!r}: {unknown}")
        advisors = [candidates[k] for k in request.roster]
    elif tier.roster == "full":
        advisors = list(candidates.values())
    else:  # core
        advisors = [p for p in candidates.values() if p.core]

    chosen_keys = {p.key for p in advisors}
    skipped = [k for k in candidates if k not in chosen_keys]

    do_peer = (
        request.peer_review_override
        if request.peer_review_override is not None
        else tier.peer_review
    )

    return CouncilSpec(
        origin="pack",
        pack_id=pack.id,
        mode=mode,
        stakes=tier.name,
        advisors=advisors,
        chairman=pack.chairman,
        prompt_set=pack.prompt_set,
        grounding=pack.grounding,
        output_contract=pack.output_contract,
        execution_policy=pack.execution_policy,
        peer_review=do_peer,
        default_model=pack.default_model,
        peer_review_pool=pack.peer_review_pool,
        peer_review_backend=pack.peer_review_backend or pack.default_backend,
        peer_review_backends=pack.peer_review_backends,
        skipped=skipped,
        roster_quality="curated",
    )


def build_dynamic_council(
    request: CouncilRequest,
    architect: PersonaArchitect,
    chairman: PersonaSpec,
    available: List[ModelAssignment],
    peer_review_pool: Optional[dict] = None,
    peer_review_backend: str = "",
    peer_review_backends: Optional[dict] = None,
    contract: Optional[DynamicCouncilContract] = None,
) -> CouncilSpec:
    contract = contract or DynamicCouncilContract()
    drafts, _raw = architect.design(request.brief, contract)
    advisor_drafts, repairs = normalize_and_repair(drafts, contract)

    assignments = assign_models(len(advisor_drafts), available, chairman_family=chairman.family)
    advisors = [compile_persona(d, a) for d, a in zip(advisor_drafts, assignments)]

    major_repair = any(r.kind in ("injected_role", "trimmed_to_cap") for r in repairs)
    quality = "repaired" if major_repair else "clean_generation"

    do_peer = request.peer_review_override if request.peer_review_override is not None else True

    return CouncilSpec(
        origin="dynamic",
        pack_id="dynamic",
        mode="default",
        stakes=request.stakes,
        advisors=advisors,
        chairman=chairman,
        prompt_set=PromptSet.load(None),
        grounding=NullGrounding(),
        output_contract=builtin_contract("generic_verdict_v1"),
        execution_policy=ExecutionPolicy(
            required_successful_roles=set(contract.required_advisor_roles),
            on_missing_required_role=MissingRoleBehavior.DEGRADE_WITH_WARNING,
            min_completed_advisors=2,
        ),
        peer_review=do_peer,
        default_model=chairman.model,
        peer_review_pool=peer_review_pool or {},
        peer_review_backend=peer_review_backend or chairman.backend,
        peer_review_backends=peer_review_backends or {},
        skipped=[],
        roster_repairs=repairs,
        roster_quality=quality,
    )
