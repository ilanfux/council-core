"""Top-level orchestration.

Route -> Build Council -> Gather Grounding -> Dispatch -> Peer Review ->
Chairman -> Validate. Routing and roster selection happen up front; the
dispatch/peer/chairman core is unchanged regardless of where the roster came
from. The orchestrator never performs UX — a ``choice_required`` route returns a
non-convened result for the caller (CLI/API) to resolve.
"""

from __future__ import annotations

import random
import uuid
from typing import Callable, Dict, List, Optional, Tuple

from council_core.backends import BackendError, BackendRegistry, BackendTask
from council_core.chairman import run_chairman
from council_core.config_loader import RuntimeConfig, available_assignments, load_runtime_config
from council_core.dispatch import dispatch_advisors
from council_core.grounding import GroundingRequest
from council_core.input import CouncilRequest, PersonaSpec
from council_core.manifest import RunManifest
from council_core.metering import MeteringSink
from council_core.model_resolve import ResolutionResult, resolve_council_models
from council_core.pack import PackDefinition, list_builtin_packs, load_pack
from council_core.persona_architect import PersonaArchitect
from council_core.policy import ExecutionPolicy, MissingRoleBehavior, RunStatus
from council_core.result import CouncilResult, ExecutionSummary, StageOutcome
from council_core.roster import build_dynamic_council, build_pack_council
from council_core.router import RouteDecision, Router
from council_core.spec import CouncilSpec


def _load_all_packs(config: RuntimeConfig) -> Dict[str, PackDefinition]:
    packs: Dict[str, PackDefinition] = {}
    for pid in list_builtin_packs():
        try:
            packs[pid] = load_pack(pid)
        except Exception:
            continue
    return packs


def _make_generate(registry: BackendRegistry, spec: Dict[str, str], cwd: str) -> Callable[[str], str]:
    backend_name = str(spec.get("backend", "google"))
    model = str(spec.get("model", ""))

    def gen(prompt: str) -> str:
        outcome = registry.get(backend_name).run_batch(
            [BackendTask(task_id="architect", prompt=prompt, model=model)], cwd=cwd
        )[0]
        return outcome.text if outcome.ok else ""

    return gen


def _dynamic_chairman(spec: Dict[str, str]) -> PersonaSpec:
    return PersonaSpec(
        key="chairman",
        title="Chairman",
        prompt="Synthesize the advisors and peer reviews into one decisive, evidence-grounded verdict.",
        model=str(spec.get("model", "")),
        family=str(spec.get("family", spec.get("backend", ""))).lower(),
        capability="heavy",
        backend=str(spec.get("backend", "google")).lower(),
        role_id="chairman",
    )


def _apply_policy(
    council: CouncilSpec,
    advisor_results,
    peer_reviews,
    chairman_ok: bool,
) -> Tuple[RunStatus, List[str]]:
    policy: ExecutionPolicy = council.execution_policy
    warnings: List[str] = []
    completed = [a for a in advisor_results if a.outcome.ok]

    status = RunStatus.COMPLETED

    # mandatory role coverage
    ok_roles = {a.persona.role_id for a in completed if a.persona.role_id}
    missing = policy.required_successful_roles - ok_roles
    if missing:
        msg = f"required role(s) did not complete: {sorted(missing)}"
        if policy.on_missing_required_role == MissingRoleBehavior.FAIL_CLOSED:
            warnings.append(f"FAIL-CLOSED: {msg}")
            status = RunStatus.FAILED
        else:
            warnings.append(f"DEGRADED: {msg}")
            status = RunStatus.DEGRADED

    if len(completed) < policy.min_completed_advisors:
        # A hard floor: below the minimum, there is not enough signal to trust a
        # verdict, so the run fails regardless of any earlier degrade.
        warnings.append(
            f"only {len(completed)} advisor(s) completed (min {policy.min_completed_advisors})."
        )
        status = RunStatus.FAILED

    if not chairman_ok and status == RunStatus.COMPLETED:
        status = RunStatus.DEGRADED
        warnings.append("chairman synthesis unavailable; showing assembled digest.")

    return status, warnings


def run_council(
    request: CouncilRequest,
    config: Optional[RuntimeConfig] = None,
    seed: Optional[int] = None,
    registry: Optional[BackendRegistry] = None,
    packs: Optional[Dict[str, PackDefinition]] = None,
    architect: Optional[PersonaArchitect] = None,
    on_assignments: Optional[Callable[[str], None]] = None,
) -> Tuple[CouncilResult, Optional[RunManifest]]:
    config = config or load_runtime_config()
    registry = registry or config.registry()
    packs = packs if packs is not None else _load_all_packs(config)
    run_id = uuid.uuid4().hex[:16]

    # Prefer deterministic scoring; inject architect backend as optional classifier.
    router_generate = None
    if not (request.pack or request.pack_path or request.dynamic):
        try:
            router_generate = _make_generate(registry, config.architect, request.cwd)
        except Exception:
            router_generate = None
    route: RouteDecision = Router(generate=router_generate).route(request, packs)

    # choice_required -> hand back to the caller; do NOT ask here.
    if route.kind == "choice_required":
        result = CouncilResult(
            convened=False, route=route, council=None, grounding=None,
            advisor_results=[], peer_reviews=[], verdict=None,
            execution=ExecutionSummary(status=RunStatus.FAILED, stages=[]),
            warnings=[f"routing needs a choice: {route.reason}"], run_id=run_id,
        )
        return result, None

    architect_raw: Optional[str] = None
    pack_version = ""

    def _not_built(error: object) -> Tuple[CouncilResult, None]:
        return (
            CouncilResult(
                convened=False, route=route, council=None, grounding=None,
                advisor_results=[], peer_reviews=[], verdict=None,
                execution=ExecutionSummary(status=RunStatus.FAILED, stages=[]),
                warnings=[f"could not build council: {error}"], run_id=run_id,
            ),
            None,
        )

    # Build the council spec (pack or dynamic). Any failure degrades to a
    # non-convened result rather than crashing the caller.
    if route.kind == "dynamic":
        try:
            arch = architect or PersonaArchitect(_make_generate(registry, config.architect, request.cwd))
            assignments = available_assignments(config, registry)
            if not assignments:
                raise BackendError("no ready backends in dynamic_pool for a dynamic council.")
            chairman = _dynamic_chairman(config.chairman)
            council = build_dynamic_council(
                request, arch, chairman, assignments,
                peer_review_backends={a.family: a.backend for a in assignments},
                peer_review_pool={a.family: a.model for a in assignments},
            )
            architect_raw = getattr(arch, "_last_raw", None)
        except Exception as error:
            return _not_built(error)
    else:
        pid = route.selected_pack or request.pack
        try:
            pack = packs.get(pid) if pid in (packs or {}) else load_pack(pid or "", request.pack_path)
            council = build_pack_council(pack, request)
            pack_version = pack.version
        except Exception as error:  # bad mode/stakes/roster/pack -> graceful, not a crash
            return _not_built(error)

    stages: List[StageOutcome] = []
    warnings: List[str] = []

    if not council.advisors:
        result = CouncilResult(
            convened=False, route=route, council=council, grounding=None,
            advisor_results=[], peer_reviews=[], verdict=None,
            execution=ExecutionSummary(status=RunStatus.FAILED, stages=stages),
            warnings=["council not convened (tier below threshold or empty roster)."],
            run_id=run_id,
        )
        return result, RunManifest.from_result(
            result, seed=seed, architect_raw=architect_raw, pack_version=pack_version
        )

    # Model cascade (Cursor → providers → UI).
    resolution: ResolutionResult = resolve_council_models(
        council,
        config,
        registry,
        ui_model=request.ui_model,
        ui_backend=request.ui_backend,
        require_cursor=request.require_cursor,
    )
    warnings.extend(resolution.warnings)
    if on_assignments is not None:
        on_assignments(resolution.summary_text())
    stages.append(
        StageOutcome("model_resolve", "completed", f"cascade tier={resolution.tier}")
    )

    if resolution.tier == "failed":
        msg = (
            "this pack needs Cursor; set CURSOR_API_KEY or drop --require-cursor "
            "to allow provider fallback"
        )
        if msg not in warnings:
            warnings.append(msg)
        result = CouncilResult(
            convened=False,
            route=route,
            council=council,
            grounding=None,
            advisor_results=[],
            peer_reviews=[],
            verdict=None,
            execution=ExecutionSummary(status=RunStatus.FAILED, stages=stages),
            warnings=warnings,
            run_id=run_id,
            model_assignments=resolution.assignments,
            cascade_tier=resolution.tier,
        )
        return result, RunManifest.from_result(
            result, seed=seed, architect_raw=architect_raw, pack_version=pack_version
        )

    meter = MeteringSink(pack=council.pack_id, stakes=council.stakes)

    # Grounding — never let a provider failure crash the run.
    from council_core.grounding import GroundingBundle

    try:
        bundle = council.grounding.gather(
            GroundingRequest(brief=request.brief, cwd=request.cwd, args=request.grounding_args)
        )
        stages.append(StageOutcome("grounding", "completed", f"{len(bundle.items)} evidence item(s)"))
    except Exception as error:
        bundle = GroundingBundle(items=(), warnings=(f"grounding provider failed: {error}",))
        stages.append(StageOutcome("grounding", "failed", str(error)))
    warnings.extend(bundle.warnings)

    # Credential pre-check (warn, don't hard-fail; failed personas are captured).
    for name in {p.backend for p in council.advisors} | {council.chairman.backend}:
        try:
            reason = registry.get(name).check_credentials()
        except BackendError as error:
            reason = str(error)
        if reason:
            warnings.append(f"backend '{name}' not ready: {reason}")

    # Dispatch
    advisor_results = dispatch_advisors(
        personas=council.advisors, brief=request.brief, mode=council.mode, cwd=request.cwd,
        grounding_text=bundle.render(), prompt_set=council.prompt_set, meter=meter, registry=registry,
    )
    ok_count = sum(1 for a in advisor_results if a.outcome.ok)
    stages.append(StageOutcome("dispatch", "completed" if ok_count else "failed", f"{ok_count}/{len(advisor_results)} ok"))

    # Peer review
    peer_reviews = []
    if council.peer_review:
        from council_core.peer_review import run_peer_review

        peer_reviews, peer_warns = run_peer_review(
            advisors=advisor_results, brief=request.brief, prompt_set=council.prompt_set, cwd=request.cwd,
            peer_review_pool=council.peer_review_pool, default_model=council.default_model,
            meter=meter, registry=registry, peer_review_backend=council.peer_review_backend,
            peer_review_backends=council.peer_review_backends,
            allow_same_family_fallback=council.execution_policy.allow_same_family_fallback,
            rng=random.Random(seed) if seed is not None else None,
        )
        warnings.extend(peer_warns)
        stages.append(StageOutcome("peer_review", "completed", f"{len(peer_reviews)} review(s)"))
    else:
        stages.append(StageOutcome("peer_review", "skipped", "tier has peer review off"))

    # Decide whether to run the chairman (fail-closed policy on missing roles).
    policy = council.execution_policy
    ok_roles = {a.persona.role_id for a in advisor_results if a.outcome.ok and a.persona.role_id}
    missing_required = policy.required_successful_roles - ok_roles
    skip_chairman = bool(missing_required) and policy.chairman_when_required_analysis_missing == "fail_closed"

    verdict = None
    contract_violations: List[str] = []
    if skip_chairman:
        stages.append(StageOutcome("chairman", "skipped", f"fail-closed: missing {sorted(missing_required)}"))
    else:
        peer_texts = [p.outcome.text for p in peer_reviews if p.outcome.ok]
        verdict = run_chairman(
            chairman=council.chairman, advisors=advisor_results, peer_reviews=peer_texts,
            brief=request.brief, prompt_set=council.prompt_set,
            output_contract=council.output_contract, cwd=request.cwd, meter=meter, registry=registry,
        )
        stages.append(StageOutcome("chairman", "completed" if verdict.ok else "failed",
                                   verdict.error_message or ""))
        if verdict.ok:
            contract_violations = council.output_contract.validate(verdict.text)
            warnings.extend(contract_violations)

    status, policy_warnings = _apply_policy(council, advisor_results, peer_reviews, bool(verdict and verdict.ok))
    warnings.extend(policy_warnings)

    result = CouncilResult(
        convened=True, route=route, council=council, grounding=bundle,
        advisor_results=advisor_results, peer_reviews=peer_reviews, verdict=verdict,
        execution=ExecutionSummary(status=status, stages=stages),
        warnings=warnings, contract_violations=contract_violations, run_id=run_id,
        model_assignments=resolution.assignments, cascade_tier=resolution.tier,
    )
    manifest = RunManifest.from_result(
        result, seed=seed, architect_raw=architect_raw, pack_version=pack_version,
    )
    return result, manifest
