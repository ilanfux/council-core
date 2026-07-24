"""Live Cursor SDK smoke (opt-in via --run-integration + CURSOR_API_KEY)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from council_core.input import CouncilRequest
from council_core.orchestrator import run_council
from council_core.pack import load_pack
from council_core.policy import RunStatus


@pytest.fixture
def require_integration(request):
    if not request.config.getoption("run_integration"):
        pytest.skip("pass --run-integration to run live Cursor tests")
    if not (os.environ.get("CURSOR_API_KEY") or "").strip():
        pytest.skip("CURSOR_API_KEY is not set")


@pytest.mark.integration
def test_live_dev_cursor_smoke(require_integration):
    packs = {"dev_cursor": load_pack("dev_cursor")}
    repo = Path(__file__).resolve().parents[1]
    result, _ = run_council(
        CouncilRequest(
            brief=(
                "Smoke: briefly review src/council_core/model_resolve.py cascade "
                "priorities. Cite path:line. Keep it short."
            ),
            pack="dev_cursor",
            mode="review",
            stakes="standard",
            cwd=str(repo),
            require_cursor=True,
        ),
        packs=packs,
        seed=1,
    )
    assert result.convened, result.warnings
    assert result.cascade_tier == "cursor"
    assert result.execution.status == RunStatus.COMPLETED
    ok = [a for a in result.advisor_results if a.outcome.ok]
    assert len(ok) >= 2
    families = {a.persona.family for a in ok}
    assert len(families) >= 2
    assert result.verdict and result.verdict.ok
