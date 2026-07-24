"""Tests for the MCP server tool logic (no ``mcp`` package needed).

The tools are plain functions with an injectable runner, so we exercise them with
a fake ``run_council`` and against the real pack/backend discovery.
"""

from __future__ import annotations

from pathlib import Path

from council_core.input import CouncilRequest
from council_core.mcp_server import _build_grounding_args, _check_backends, _convene, _list_packs
from council_core.result import CouncilResult, ExecutionSummary
from council_core.policy import RunStatus


def _fake_result(**over) -> CouncilResult:
    # convened=False keeps the fake self-consistent (a convened result always
    # carries a council); these tests only need request pass-through + the dict.
    return CouncilResult(
        convened=over.get("convened", False),
        route=None,
        council=None,
        grounding=None,
        advisor_results=[],
        peer_reviews=[],
        verdict=None,
        execution=ExecutionSummary(status=over.get("status", RunStatus.COMPLETED), stages=[]),
        warnings=over.get("warnings", []),
        run_id="testrun",
    )


def test_convene_passes_request_through():
    captured = {}

    def fake_run(request: CouncilRequest):
        captured["req"] = request
        return _fake_result(), None

    out = _convene(brief="review this", pack="dev", mode="review", _run=fake_run)
    req = captured["req"]
    assert req.brief == "review this"
    assert req.pack == "dev" and req.mode == "review"
    assert out["run_id"] == "testrun"
    assert "markdown" in out  # result_to_dict projection


def test_convene_stages_inline_documents_and_cleans_up(tmp_path):
    seen = {}

    def fake_run(request: CouncilRequest):
        # capture the staged path + assert the file exists during the run
        docs = request.grounding_args.get("documents", "")
        seen["docs"] = docs
        label, _, path = docs.partition("::")
        seen["exists_during_run"] = Path(path).is_file()
        seen["path"] = path
        return _fake_result(), None

    _convene(brief="q", inline_documents={"payslip": "NET 12,345"}, _run=fake_run)
    assert "payslip::" in seen["docs"]
    assert seen["exists_during_run"] is True
    # temp dir is removed after the call
    assert not Path(seen["path"]).exists()


def test_build_grounding_args_combines_paths_and_inline(tmp_path):
    holder = []
    args = _build_grounding_args(
        documents=["notes::C:/x/notes.md"],
        inline_documents={"ages": "10, 13, 16"},
        tmp_holder=holder,
    )
    lines = args["documents"].splitlines()
    assert any(line.startswith("notes::") for line in lines)
    assert any(line.startswith("ages::") for line in lines)
    assert holder  # a temp dir was created and recorded for cleanup


def test_list_packs_reports_builtins():
    packs = {p["id"]: p for p in _list_packs()}
    assert {"dev", "finance", "career", "travel"} <= set(packs)
    assert "review" in packs["dev"]["modes"]
    assert packs["travel"]["grounding"] == "documents"


def test_check_backends_shape():
    status = _check_backends()
    assert isinstance(status, dict) and status
    # values are "ready" or a human reason string
    assert all(isinstance(v, str) for v in status.values())
