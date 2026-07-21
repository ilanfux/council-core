"""RunManifest: the persisted, replayable record of a council run (Pydantic).

Replay semantics: the manifest guarantees PLAN/INPUT reproducibility — the exact
CouncilSpec, prompts (by template hash), roster, repairs, seed, and model/backend
assignments can be reconstructed for audit, debugging, and promotion. It does NOT
guarantee identical OUTPUT: LLM sampling is non-deterministic and the seed only
controls our RNG (anonymization order, reviewer pairing). If a model is later
deprecated, replay runs on a substitute, recorded as such.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from council_core import __version__
from council_core.result import CouncilResult


class PersonaRecord(BaseModel):
    key: str
    title: str
    role_id: Optional[str] = None
    backend: str
    model: str
    family: str


class RepairRecord(BaseModel):
    kind: str
    detail: str


class StageRecord(BaseModel):
    stage: str
    status: str
    detail: str = ""
    attempts: int = 1


class RunManifest(BaseModel):
    run_id: str
    engine_version: str = __version__
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    pack_id: str
    pack_version: str = ""
    origin: str                       # "pack" | "dynamic"
    mode: str
    stakes: str
    prompt_template_versions: Dict[str, str] = Field(default_factory=dict)
    route_kind: str = ""
    route_selected_pack: Optional[str] = None
    route_confidence: float = 0.0
    architect_raw_output: Optional[str] = None
    roster_repairs: List[RepairRecord] = Field(default_factory=list)
    roster_quality: str = "curated"
    advisors: List[PersonaRecord] = Field(default_factory=list)
    chairman: Optional[PersonaRecord] = None
    output_schema: str = ""
    execution_status: str = ""
    stage_outcomes: List[StageRecord] = Field(default_factory=list)
    seed: Optional[int] = None
    grounding_provider: str = ""
    grounding_token_estimate: int = 0
    warnings: List[str] = Field(default_factory=list)

    @classmethod
    def from_result(
        cls,
        result: CouncilResult,
        seed: Optional[int] = None,
        architect_raw: Optional[str] = None,
        pack_version: str = "",
    ) -> "RunManifest":
        spec = result.council

        def rec(p) -> PersonaRecord:
            return PersonaRecord(
                key=p.key, title=p.title, role_id=p.role_id,
                backend=p.backend, model=p.model, family=p.family,
            )

        return cls(
            run_id=result.run_id,
            pack_id=spec.pack_id if spec else "",
            pack_version=pack_version,
            origin=spec.origin if spec else "",
            mode=spec.mode if spec else "",
            stakes=spec.stakes if spec else "",
            prompt_template_versions=(spec.prompt_set.versions if spec else {}),
            route_kind=(result.route.kind if result.route else ""),
            route_selected_pack=(result.route.selected_pack if result.route else None),
            route_confidence=(result.route.confidence if result.route else 0.0),
            architect_raw_output=architect_raw,
            roster_repairs=[RepairRecord(kind=r.kind, detail=r.detail) for r in (spec.roster_repairs if spec else [])],
            roster_quality=(spec.roster_quality if spec else "curated"),
            advisors=[rec(p) for p in (spec.advisors if spec else [])],
            chairman=(rec(spec.chairman) if spec else None),
            output_schema=(spec.output_contract.schema_id if spec else ""),
            execution_status=result.execution.status.value,
            stage_outcomes=[
                StageRecord(stage=s.stage, status=s.status, detail=s.detail, attempts=s.attempts)
                for s in result.execution.stages
            ],
            seed=seed,
            grounding_provider=(getattr(spec.grounding, "name", "") if spec else ""),
            grounding_token_estimate=(result.grounding.token_estimate if result.grounding else 0),
            warnings=list(result.warnings),
        )
