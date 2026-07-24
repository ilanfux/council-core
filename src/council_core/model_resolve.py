"""Model assignment resolution with a graceful fallback cascade.

Priority A — Cursor SDK: validate/fallback Cursor model ids against the live
catalog (never invent a slug); drop unsupported family-specific params.
Priority B — configured provider APIs: if Cursor is missing or unusable, remap
cursor-backed personas onto ready provider assignments (``dynamic_pool``).
Priority C — UI model: if no providers are ready either, force every persona
onto the skill's local UI model (``CouncilRequest.ui_model`` / ``COUNCIL_UI_MODEL``).

Never hard-fails the run for missing Cursor. Pure-provider packs skip discovery
entirely via ``cursor_needed_for``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from council_core.backends.base import BackendError
from council_core.config_loader import RuntimeConfig, available_assignments
from council_core.input import PersonaSpec
from council_core.persona_architect import ModelAssignment
from council_core.sdk_client import ModelParamCatalog, SdkUnavailableError, discover_models
from council_core.spec import CouncilSpec


@dataclass
class PersonaAssignment:
    role: str  # "advisor" | "chairman"
    key: str
    title: str
    backend: str
    model: str
    family: str
    note: str = ""


@dataclass
class ResolutionResult:
    """Outcome of the cascade for one council."""

    tier: str  # "cursor" | "providers" | "ui" | "unchanged"
    assignments: List[PersonaAssignment] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def summary_text(self) -> str:
        lines = [
            f"Model assignments (cascade tier: {self.tier}):",
            f"  {'role':<10} {'persona':<28} {'backend':<12} model",
            f"  {'-' * 10} {'-' * 28} {'-' * 12} {'-' * 32}",
        ]
        for a in self.assignments:
            note = f"  ({a.note})" if a.note else ""
            lines.append(
                f"  {a.role:<10} {a.title:<28} {a.backend:<12} {a.model}{note}"
            )
        return "\n".join(lines)


DiscoverFn = Callable[[Optional[str]], Tuple[List[str], ModelParamCatalog]]


def cursor_needed_for(council: CouncilSpec) -> bool:
    """True when the SELECTED roster requires Cursor model discovery."""

    if council.chairman.backend == "cursor":
        return True
    if any(p.backend == "cursor" for p in council.advisors):
        return True
    if council.peer_review:
        if council.peer_review_backend == "cursor":
            return True
        if any(b == "cursor" for b in council.peer_review_backends.values()):
            return True
    return False


def _copy_council_personas(council: CouncilSpec) -> None:
    """Replace shared pack PersonaSpecs with copies so resolution never mutates packs."""

    council.advisors = [replace(p, model_params=dict(p.model_params)) for p in council.advisors]
    council.chairman = replace(
        council.chairman, model_params=dict(council.chairman.model_params)
    )
    council.peer_review_pool = dict(council.peer_review_pool)
    council.peer_review_backends = dict(council.peer_review_backends)


def _snapshot(council: CouncilSpec, notes: Optional[Dict[str, str]] = None) -> List[PersonaAssignment]:
    notes = notes or {}
    out = [
        PersonaAssignment(
            role="advisor",
            key=p.key,
            title=p.title,
            backend=p.backend,
            model=p.model,
            family=p.family,
            note=notes.get(p.key, ""),
        )
        for p in council.advisors
    ]
    out.append(
        PersonaAssignment(
            role="chairman",
            key=council.chairman.key,
            title=council.chairman.title,
            backend=council.chairman.backend,
            model=council.chairman.model,
            family=council.chairman.family,
            note=notes.get(council.chairman.key, notes.get("chairman", "")),
        )
    )
    return out


def resolve_cursor_models(council: CouncilSpec, available: Sequence[str]) -> List[str]:
    """Fall back any cursor-backed model id not in ``available`` to ``default_model``.

    Never invents a slug. Empty ``available`` → no rewriting (caller decides cascade).
    Returns warnings.
    """

    if not available:
        return []

    available_set = set(available)
    warnings: List[str] = []
    default = council.default_model

    if default and default not in available_set:
        # Prefer a peer-review pool cursor model, else a deterministic catalog pick.
        pool_cursor = None
        for fam, mid in council.peer_review_pool.items():
            backend = council.peer_review_backends.get(fam, council.peer_review_backend)
            if backend == "cursor" and mid in available_set:
                pool_cursor = mid
                break
        replacement = pool_cursor or sorted(available_set)[0]
        warnings.append(
            f"default_model '{default}' unavailable -> using '{replacement}' as fallback"
        )
        council.default_model = replacement
        default = replacement

    def resolve(model_id: str, label: str) -> Tuple[str, bool]:
        if not model_id:
            return default, bool(default)
        if model_id in available_set:
            return model_id, False
        warnings.append(f"{label}: model '{model_id}' unavailable -> falling back to '{default}'")
        return default, True

    if council.chairman.backend == "cursor":
        resolved, changed = resolve(council.chairman.model, "chairman")
        if changed:
            council.chairman = replace(council.chairman, model=resolved, model_params={})
        else:
            council.chairman = replace(council.chairman, model=resolved)

    for i, persona in enumerate(council.advisors):
        if persona.backend != "cursor":
            continue
        resolved, changed = resolve(persona.model, persona.key)
        if changed:
            council.advisors[i] = replace(persona, model=resolved, model_params={})
        else:
            council.advisors[i] = replace(persona, model=resolved)

    # Peer-review pool: only cursor-backed entries are validated against the catalog.
    new_pool: Dict[str, str] = {}
    for family, model_id in council.peer_review_pool.items():
        backend = council.peer_review_backends.get(family, council.peer_review_backend)
        if backend == "cursor":
            resolved, _ = resolve(model_id, f"peer_review_pool[{family}]")
            new_pool[family] = resolved
        else:
            new_pool[family] = model_id
    council.peer_review_pool = new_pool
    return warnings


def validate_model_params(council: CouncilSpec, param_catalog: ModelParamCatalog) -> List[str]:
    """Drop params the resolved Cursor model does not support. Returns warnings."""

    if not param_catalog:
        return []

    warnings: List[str] = []

    def clean(model_id: str, params: Dict[str, str], label: str) -> Dict[str, str]:
        if not params:
            return params
        supported = param_catalog.get(model_id)
        if supported is None:
            return params
        cleaned: Dict[str, str] = {}
        for key, value in params.items():
            if key not in supported:
                warnings.append(
                    f"{label}: param '{key}' is not supported by '{model_id}' -> dropped"
                )
                continue
            allowed = supported[key]
            if allowed and str(value) not in allowed:
                warnings.append(
                    f"{label}: value '{value}' invalid for '{key}' on '{model_id}' "
                    f"(allowed: {', '.join(sorted(allowed))}) -> dropped"
                )
                continue
            cleaned[key] = value
        return cleaned

    if council.chairman.backend == "cursor":
        cleaned = clean(council.chairman.model, council.chairman.model_params, "chairman")
        council.chairman = replace(council.chairman, model_params=cleaned)

    for i, persona in enumerate(council.advisors):
        if persona.backend != "cursor":
            continue
        cleaned = clean(persona.model, persona.model_params, persona.key)
        council.advisors[i] = replace(persona, model_params=cleaned)

    return warnings


def _remap_cursor_to_providers(
    council: CouncilSpec, assignments: Sequence[ModelAssignment]
) -> List[str]:
    """Priority B: move cursor-backed roles onto ready provider assignments."""

    if not assignments:
        return ["no ready provider assignments for Cursor fallback"]

    warnings: List[str] = [
        "Cursor unavailable or unusable; cascading to configured provider APIs"
    ]
    # Round-robin across ready assignments for diversity.
    idx = 0

    def next_assignment() -> ModelAssignment:
        nonlocal idx
        a = assignments[idx % len(assignments)]
        idx += 1
        return a

    def apply(persona: PersonaSpec, label: str) -> PersonaSpec:
        if persona.backend != "cursor":
            return persona
        a = next_assignment()
        warnings.append(
            f"{label}: cursor:{persona.model} -> {a.backend}:{a.model} (provider fallback)"
        )
        return replace(
            persona,
            backend=a.backend,
            model=a.model,
            family=a.family,
            model_params={},
        )

    council.chairman = apply(council.chairman, "chairman")
    council.advisors = [apply(p, p.key) for p in council.advisors]

    # Peer review: if the shared peer backend was cursor, point it at a provider.
    if council.peer_review_backend == "cursor":
        a = assignments[0]
        council.peer_review_backend = a.backend
        warnings.append(f"peer_review_backend: cursor -> {a.backend}")

    new_backends = dict(council.peer_review_backends)
    new_pool = dict(council.peer_review_pool)
    for family, backend in list(new_backends.items()):
        if backend == "cursor":
            a = next_assignment()
            new_backends[family] = a.backend
            new_pool[family] = a.model
            warnings.append(f"peer_review[{family}]: cursor -> {a.backend}:{a.model}")
    # Also rewrite pool entries whose backend (via default) is cursor.
    for family, model_id in list(new_pool.items()):
        backend = new_backends.get(family, council.peer_review_backend)
        if backend == "cursor":
            a = next_assignment()
            new_backends[family] = a.backend
            new_pool[family] = a.model
            warnings.append(
                f"peer_review_pool[{family}]: cursor:{model_id} -> {a.backend}:{a.model}"
            )
    council.peer_review_backends = new_backends
    council.peer_review_pool = new_pool

    if council.default_model and any(
        p.backend != "cursor" for p in council.advisors
    ):
        # Keep default_model coherent with a ready provider model.
        council.default_model = assignments[0].model

    return warnings


def _force_ui_model(
    council: CouncilSpec, ui_model: str, ui_backend: str
) -> List[str]:
    """Priority C: every persona runs on the skill's local UI model."""

    warnings = [
        f"No Cursor and no ready provider APIs; forcing all personas to UI model "
        f"{ui_backend}:{ui_model}"
    ]

    def apply(persona: PersonaSpec) -> PersonaSpec:
        return replace(
            persona,
            backend=ui_backend,
            model=ui_model,
            family=ui_backend,
            model_params={},
        )

    council.chairman = apply(council.chairman)
    council.advisors = [apply(p) for p in council.advisors]
    council.default_model = ui_model
    council.peer_review_backend = ui_backend
    council.peer_review_backends = {
        fam: ui_backend for fam in council.peer_review_backends
    } or {ui_backend: ui_backend}
    council.peer_review_pool = {ui_backend: ui_model}
    return warnings


def _resolve_ui_model(
    explicit_model: Optional[str], explicit_backend: Optional[str]
) -> Tuple[Optional[str], str]:
    model = (explicit_model or os.environ.get("COUNCIL_UI_MODEL") or "").strip() or None
    backend = (
        explicit_backend
        or os.environ.get("COUNCIL_UI_BACKEND")
        or "cursor"
    ).strip().lower()
    return model, backend


def _try_discover(
    api_key: Optional[str],
    discover: DiscoverFn,
) -> Tuple[Optional[List[str]], ModelParamCatalog, List[str]]:
    """Best-effort Cursor discovery. Never raises — cascade handles absence."""

    try:
        available, catalog = discover(api_key)
        if not available:
            return None, {}, ["Cursor model catalog empty"]
        return list(available), catalog, []
    except SdkUnavailableError as error:
        return None, {}, [f"Cursor unavailable: {error}"]
    except Exception as error:  # pragma: no cover - network/SDK flakiness
        return None, {}, [f"Cursor discovery failed: {error}"]


def resolve_council_models(
    council: CouncilSpec,
    config: RuntimeConfig,
    registry,
    *,
    api_key: Optional[str] = None,
    ui_model: Optional[str] = None,
    ui_backend: Optional[str] = None,
    discover: Optional[DiscoverFn] = None,
) -> ResolutionResult:
    """Apply the A→B→C cascade. Mutates a *copy* of personas on ``council``."""

    _copy_council_personas(council)
    discover = discover or discover_models
    warnings: List[str] = []

    # Pure provider packs: leave assignments alone (no Cursor key required).
    if not cursor_needed_for(council):
        return ResolutionResult(
            tier="unchanged",
            assignments=_snapshot(council),
            warnings=[],
        )

    # --- Priority A: Cursor SDK ---
    available, catalog, discover_warnings = _try_discover(api_key, discover)
    warnings.extend(discover_warnings)

    if available is not None:
        warnings.extend(resolve_cursor_models(council, available))
        warnings.extend(validate_model_params(council, catalog))
        # If after resolution any cursor persona still has an empty model, cascade.
        still_broken = [
            p for p in [council.chairman, *council.advisors]
            if p.backend == "cursor" and not p.model
        ]
        if not still_broken:
            return ResolutionResult(
                tier="cursor",
                assignments=_snapshot(council),
                warnings=warnings,
            )
        warnings.append("Cursor resolution left empty model ids; cascading to providers")

    # --- Priority B: configured provider APIs ---
    try:
        provider_pool = available_assignments(config, registry)
    except BackendError:
        provider_pool = []

    # Also accept non-cursor personas already on the roster as proof providers work,
    # but remapping needs explicit pool entries.
    if provider_pool:
        warnings.extend(_remap_cursor_to_providers(council, provider_pool))
        return ResolutionResult(
            tier="providers",
            assignments=_snapshot(council),
            warnings=warnings,
        )

    # --- Priority C: skill UI model ---
    model, backend = _resolve_ui_model(ui_model, ui_backend)
    if model:
        warnings.extend(_force_ui_model(council, model, backend))
        return ResolutionResult(
            tier="ui",
            assignments=_snapshot(council),
            warnings=warnings,
        )

    warnings.append(
        "Cascade exhausted: Cursor down, no ready provider APIs, and no "
        "COUNCIL_UI_MODEL/--ui-model; leaving configured Cursor assignments "
        "(personas may fail individually)."
    )
    return ResolutionResult(
        tier="unchanged",
        assignments=_snapshot(council),
        warnings=warnings,
    )
