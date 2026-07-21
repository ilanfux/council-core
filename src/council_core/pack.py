"""Packs: the unit of domain variability.

A pack is a directory with a versioned ``pack.yaml`` manifest that points to its
personas, prompts, grounding provider, output contract, tiers, and execution
policy. Everything loads into ONE normalized ``PackDefinition`` that the engine
consumes — no engine module ever checks ``if pack == "finance"``.

Discovery/loading/normalization/validation live here as cohesive functions
(deliberately not four classes for three packs; split later if it earns it).

Resolution order for ``load_pack(name_or_path)``:
  1. an explicit filesystem path (dir containing pack.yaml)
  2. the user pack dir ``~/.council/packs/<id>``
  3. the built-in packs shipped in ``council_core/builtin_packs/<id>``
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

import yaml
from pydantic import BaseModel, Field, ValidationError

from council_core.grounding import Grounding, get_grounding
from council_core.input import PersonaSpec
from council_core.output import OutputContract, builtin_contract, load_contract_file
from council_core.policy import ExecutionPolicy
from council_core.prompts import PromptSet

BUILTIN_DIR = Path(__file__).parent / "builtin_packs"
USER_PACK_DIR = Path(os.path.expanduser("~")) / ".council" / "packs"


# --------------------------------------------------------------------------- #
# Manifest (untrusted boundary -> Pydantic)                                    #
# --------------------------------------------------------------------------- #

class _RoutingCfg(BaseModel):
    triggers_file: Optional[str] = None
    triggers: List[str] = Field(default_factory=list)


class _CouncilCfg(BaseModel):
    personas_file: str = "personas.yaml"
    tiers_file: Optional[str] = None


class _PromptsCfg(BaseModel):
    directory: str = "prompts"


class _GroundingCfg(BaseModel):
    provider: str = "null"


class _OutputCfg(BaseModel):
    schema_id: Optional[str] = Field(default=None, alias="schema")
    schema_file: Optional[str] = None

    model_config = {"populate_by_name": True}


class _ModelsCfg(BaseModel):
    policy_file: Optional[str] = None


class _ExecutionCfg(BaseModel):
    policy_file: Optional[str] = None


class PackManifest(BaseModel):
    schema_version: int = 1
    id: str
    version: str = "0.0.0"
    display_name: str = ""
    routing: _RoutingCfg = Field(default_factory=_RoutingCfg)
    council: _CouncilCfg = Field(default_factory=_CouncilCfg)
    prompts: _PromptsCfg = Field(default_factory=_PromptsCfg)
    grounding: _GroundingCfg = Field(default_factory=_GroundingCfg)
    output: _OutputCfg = Field(default_factory=_OutputCfg)
    models: _ModelsCfg = Field(default_factory=_ModelsCfg)
    execution: _ExecutionCfg = Field(default_factory=_ExecutionCfg)


# --------------------------------------------------------------------------- #
# Normalized in-memory definition (dataclasses)                                #
# --------------------------------------------------------------------------- #

@dataclass
class Tier:
    name: str
    convene: bool = True
    roster: str = "core"          # "core" | "full"
    peer_review: bool = False
    description: str = ""


_DEFAULT_TIERS: Dict[str, Tier] = {
    "trivial": Tier("trivial", convene=False, description="Too small to convene."),
    "standard": Tier("standard", convene=True, roster="core", peer_review=False,
                     description="Everyday decision. Core roster, no peer review."),
    "thorough": Tier("thorough", convene=True, roster="full", peer_review=True,
                     description="Material/complex. Full roster + peer review."),
}


@dataclass
class PackDefinition:
    id: str
    version: str
    display_name: str
    triggers: List[str]
    modes: List[str]
    default_mode: str
    chairman: PersonaSpec
    personas: Dict[str, PersonaSpec]
    persona_modes: Dict[str, Set[str]]
    tiers: Dict[str, Tier]
    prompt_set: PromptSet
    grounding: Grounding
    output_contract: OutputContract
    execution_policy: ExecutionPolicy
    default_backend: str = "cursor"
    default_model: str = ""
    peer_review_pool: Dict[str, str] = field(default_factory=dict)
    peer_review_backend: str = ""
    peer_review_backends: Dict[str, str] = field(default_factory=dict)
    source_path: Optional[Path] = None

    def get_tier(self, stakes: str) -> Tier:
        key = (stakes or "standard").strip().lower()
        if key not in self.tiers:
            raise ValueError(f"unknown stakes tier {stakes!r}; known: {sorted(self.tiers)}")
        return self.tiers[key]

    def personas_for_mode(self, mode: str) -> Dict[str, PersonaSpec]:
        return {
            k: p for k, p in self.personas.items()
            if mode in self.persona_modes.get(k, set())
        }


class PackError(RuntimeError):
    """A pack cannot be loaded or is invalid."""


# --------------------------------------------------------------------------- #
# Loading                                                                      #
# --------------------------------------------------------------------------- #

def _persona_from_dict(key: str, raw: dict, default_backend: str, default_model: str) -> PersonaSpec:
    prompt = raw.get("prompt") or raw.get("lens") or raw.get("system_prompt") or ""
    return PersonaSpec(
        key=key,
        title=str(raw.get("title", key)),
        prompt=str(prompt).strip(),
        model=str(raw.get("model") or default_model).strip(),
        family=str(raw.get("family", "")).strip().lower(),
        capability=str(raw.get("capability", "medium")).strip().lower(),
        core=bool(raw.get("core", False)),
        triggers=[str(t).strip().lower() for t in (raw.get("triggers") or [])],
        model_params={str(k): str(v) for k, v in (raw.get("model_params") or {}).items()},
        backend=str(raw.get("backend") or default_backend).strip().lower(),
        role_id=(str(raw["role_id"]).strip() if raw.get("role_id") else None),
    )


def _read_yaml(path: Path) -> dict:
    if not path.is_file():
        raise PackError(f"expected file not found: {path}")
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as error:
        raise PackError(f"malformed YAML in {path}: {error}") from error


def _pack_file(pack_dir: Path, name: str) -> Path:
    """Resolve a manifest-referenced file, keeping it inside the pack directory.

    A pack manifest declares relative file names; containing them within the
    pack dir prevents a stray ``..`` (typo or a malicious external pack) from
    reaching arbitrary files, which matters once external packs are loaded.
    """

    base = pack_dir.resolve()
    resolved = (base / name).resolve()
    if base != resolved and base not in resolved.parents:
        raise PackError(f"pack file '{name}' escapes the pack directory {base}")
    return resolved


def _resolve_pack_dir(name_or_path: str, pack_path: Optional[str] = None) -> Path:
    if pack_path:
        p = Path(pack_path)
        if (p / "pack.yaml").is_file():
            return p
        raise PackError(f"--pack-path has no pack.yaml: {pack_path}")
    # explicit path?
    maybe = Path(name_or_path)
    if (maybe / "pack.yaml").is_file():
        return maybe
    # user dir
    user = USER_PACK_DIR / name_or_path
    if (user / "pack.yaml").is_file():
        return user
    # built-in
    builtin = BUILTIN_DIR / name_or_path
    if (builtin / "pack.yaml").is_file():
        return builtin
    raise PackError(
        f"pack '{name_or_path}' not found (looked in explicit path, "
        f"{USER_PACK_DIR}, and {BUILTIN_DIR})."
    )


def load_pack(name_or_path: str, pack_path: Optional[str] = None) -> PackDefinition:
    pack_dir = _resolve_pack_dir(name_or_path, pack_path)
    raw_manifest = _read_yaml(pack_dir / "pack.yaml")
    try:
        manifest = PackManifest.model_validate(raw_manifest)
    except ValidationError as error:
        raise PackError(f"invalid pack.yaml in {pack_dir}:\n{error}") from error

    # personas + tiers + modes
    council_raw = _read_yaml(_pack_file(pack_dir, manifest.council.personas_file))
    default_backend = str(council_raw.get("default_backend", "cursor")).strip().lower()
    default_model = str(council_raw.get("default_model", "")).strip()

    declared_modes = [str(m).strip() for m in (council_raw.get("modes") or [])] or ["default"]
    default_mode = declared_modes[0]

    # chairman (separate role)
    chairman_raw = council_raw.get("chairman")
    if not isinstance(chairman_raw, dict):
        raise PackError(f"{manifest.id}: personas file must define a 'chairman:' mapping")
    chairman = _persona_from_dict("chairman", chairman_raw, default_backend, default_model)
    chairman.role_id = "chairman"

    personas: Dict[str, PersonaSpec] = {}
    persona_modes: Dict[str, Set[str]] = {}
    for key, raw in (council_raw.get("personas") or {}).items():
        if not isinstance(raw, dict):
            raise PackError(f"{manifest.id}: persona '{key}' must be a mapping, got {type(raw).__name__}")
        persona = _persona_from_dict(key, raw, default_backend, default_model)
        personas[key] = persona
        modes = {str(m).strip() for m in (raw.get("modes") or [])} or set(declared_modes)
        persona_modes[key] = modes

    if not personas:
        raise PackError(f"{manifest.id}: no advisor personas defined")

    # tiers
    tiers = dict(_DEFAULT_TIERS)
    tiers_file = manifest.council.tiers_file
    if tiers_file:
        tiers_raw = _read_yaml(_pack_file(pack_dir, tiers_file))
        loaded: Dict[str, Tier] = {}
        for name, spec in (tiers_raw.get("tiers") or {}).items():
            spec = spec or {}
            loaded[name] = Tier(
                name=name,
                convene=bool(spec.get("convene", True)),
                roster=str(spec.get("roster", "core")).strip().lower(),
                peer_review=bool(spec.get("peer_review", False)),
                description=str(spec.get("description", "")),
            )
        if not loaded:
            # The author declared a tiers file but it defined no tiers — surface
            # the mismatch rather than silently using defaults.
            raise PackError(f"{manifest.id}: tiers_file '{tiers_file}' defines no tiers")
        tiers = loaded

    # prompts
    prompt_dir = _pack_file(pack_dir, manifest.prompts.directory)
    prompt_set = PromptSet.load(prompt_dir if prompt_dir.is_dir() else None)

    # grounding
    try:
        grounding = get_grounding(manifest.grounding.provider)
    except ValueError as error:
        raise PackError(f"{manifest.id}: {error}") from error

    # output contract
    try:
        if manifest.output.schema_file:
            output_contract = load_contract_file(_pack_file(pack_dir, manifest.output.schema_file))
        else:
            output_contract = builtin_contract(manifest.output.schema_id or "generic_verdict_v1")
    except ValueError as error:
        raise PackError(f"{manifest.id}: {error}") from error

    # execution policy
    if manifest.execution.policy_file:
        exec_raw = _read_yaml(_pack_file(pack_dir, manifest.execution.policy_file))
        execution_policy = ExecutionPolicy.from_dict(exec_raw)
    else:
        execution_policy = ExecutionPolicy()

    # triggers
    triggers = list(manifest.routing.triggers)
    if manifest.routing.triggers_file:
        trig_raw = _read_yaml(_pack_file(pack_dir, manifest.routing.triggers_file))
        triggers.extend(str(t).strip().lower() for t in (trig_raw.get("triggers") or []))

    definition = PackDefinition(
        id=manifest.id,
        version=manifest.version,
        display_name=manifest.display_name or manifest.id,
        triggers=[t.lower() for t in triggers],
        modes=declared_modes,
        default_mode=default_mode,
        chairman=chairman,
        personas=personas,
        persona_modes=persona_modes,
        tiers=tiers,
        prompt_set=prompt_set,
        grounding=grounding,
        output_contract=output_contract,
        execution_policy=execution_policy,
        default_backend=default_backend,
        default_model=default_model,
        peer_review_pool={
            str(k).lower(): str(v) for k, v in (council_raw.get("peer_review_pool") or {}).items()
        },
        peer_review_backend=str(council_raw.get("peer_review_backend", default_backend)).strip().lower(),
        peer_review_backends={
            str(k).lower(): str(v).strip().lower()
            for k, v in (council_raw.get("peer_review_backends") or {}).items()
        },
        source_path=pack_dir,
    )
    _validate(definition)
    return definition


def _validate(pack: PackDefinition) -> None:
    if pack.default_mode not in pack.modes:
        raise PackError(f"{pack.id}: default_mode '{pack.default_mode}' not in modes {pack.modes}")
    for key, modes in pack.persona_modes.items():
        unknown = modes - set(pack.modes)
        if unknown:
            raise PackError(f"{pack.id}: persona '{key}' references unknown modes {sorted(unknown)}")
    # every mode should have at least one persona
    for mode in pack.modes:
        if not pack.personas_for_mode(mode):
            raise PackError(f"{pack.id}: mode '{mode}' has no personas")
    # every dispatched agent must resolve a model (else a cryptic runtime failure)
    if not pack.chairman.model:
        raise PackError(f"{pack.id}: chairman has no model (set a model or default_model)")
    for key, persona in pack.personas.items():
        if not persona.model:
            raise PackError(f"{pack.id}: persona '{key}' has no model (set a model or default_model)")


def list_builtin_packs() -> List[str]:
    if not BUILTIN_DIR.is_dir():
        return []
    return sorted(
        d.name for d in BUILTIN_DIR.iterdir() if (d / "pack.yaml").is_file()
    )
