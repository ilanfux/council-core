"""End-to-end characterization with fake backends (no network)."""

from __future__ import annotations

import pytest

from council_core.input import CouncilRequest
from council_core.pack import load_pack
from council_core.persona_architect import PersonaArchitect
from council_core.orchestrator import run_council
from council_core.policy import RunStatus

from conftest import FakeBackend, FakeRegistry


@pytest.fixture
def packs():
    return {p: load_pack(p) for p in ("dev", "finance", "career")}


def test_pack_run_dev_completes(packs, fake_registry):
    req = CouncilRequest(brief="review this PR", pack="dev", mode="review", stakes="standard")
    result, manifest = run_council(req, registry=fake_registry, packs=packs, seed=7)
    assert result.convened
    assert result.execution.status == RunStatus.COMPLETED
    assert result.verdict and result.verdict.ok
    assert result.council.chairman.key == "chairman"
    assert "chairman" not in {a.persona.key for a in result.advisor_results}
    assert len(result.advisor_results) == 4  # dev review core roster
    assert not result.contract_violations
    # manifest projection
    assert manifest.origin == "pack" and manifest.pack_id == "dev"
    assert manifest.chairman is not None
    assert len(manifest.advisors) == 4
    assert manifest.prompt_template_versions  # recorded


def test_finance_fail_closed_on_missing_fact_analyst(packs):
    reg = FakeRegistry(FakeBackend(fail_keys={"fact_analyst"}))
    req = CouncilRequest(brief="keren hishtalmut withdrawal after termination", pack="finance", stakes="standard")
    result, manifest = run_council(req, registry=reg, packs=packs)
    assert result.execution.status == RunStatus.FAILED
    # chairman must be skipped when a mandatory role failed (fail-closed)
    assert result.verdict is None
    stage = {s.stage: s.status for s in result.execution.stages}
    assert stage.get("chairman") == "skipped"


def test_dynamic_council(packs):
    raw = '[{"role_id":"distributed_systems_expert","title":"Distributed Systems Expert","objective":"scaling"}]'
    architect = PersonaArchitect(lambda prompt: raw)
    reg = FakeRegistry()
    req = CouncilRequest(brief="design a novel realtime kite-racing telemetry system", dynamic=True)
    result, manifest = run_council(req, registry=reg, packs=packs, architect=architect, seed=1)
    assert result.convened
    assert result.council.origin == "dynamic"
    ids = {a.persona.role_id for a in result.advisor_results if a.persona.role_id}
    assert {"risk_auditor", "fact_analyst"} <= ids
    assert len(result.advisor_results) <= 4
    assert manifest.origin == "dynamic"
    assert manifest.architect_raw_output == raw


def test_choice_required_not_convened(packs, fake_registry):
    req = CouncilRequest(brief="what wine pairs with fish")
    result, manifest = run_council(req, registry=fake_registry, packs=packs)
    assert not result.convened
    assert result.route.kind == "choice_required"
    assert manifest is None
