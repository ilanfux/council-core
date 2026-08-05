"""Regression tests for the evidence floor.

Incident being pinned: a `dev` review ran against a directory that was not a git
repo. Grounding produced 0 evidence items, the run still reported COMPLETED, and
the advisors returned confident findings about code they had never seen —
including a ZeroDivisionError that did not exist — while missing a requirement
violation that lived in a spec file nobody attached.

Two defects, two floors:
  * grounding must fall back to the working tree instead of returning nothing
  * a council with no evidence must fail closed, not report COMPLETED
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from council_core.grounding import GroundingRequest
from council_core.grounding.git_repo import GitRepoGrounding
from council_core.input import CouncilRequest
from council_core.orchestrator import _apply_policy, run_council
from council_core.pack import load_pack
from council_core.policy import ExecutionPolicy, MissingRoleBehavior, RunStatus


# --------------------------------------------------------------------------
# grounding: never hand back an empty bundle when files exist
# --------------------------------------------------------------------------

def _write_project(tmp_path):
    (tmp_path / "brief.md").write_text(
        "# Spec\nA report must include every SKU present in the input.\n",
        encoding="utf-8",
    )
    (tmp_path / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    return tmp_path


def test_non_git_directory_falls_back_to_working_tree(tmp_path):
    """The exact incident: no .git, so git yields nothing."""
    _write_project(tmp_path)

    bundle = GitRepoGrounding().gather(
        GroundingRequest(brief="review this", cwd=str(tmp_path), args={})
    )

    assert bundle.has_evidence, "a non-git directory must still ground the review"
    names = {i.source_id for i in bundle.items}
    assert "app.py" in names
    assert "brief.md" in names
    assert any("fell back to reading" in w for w in bundle.warnings)


def test_spec_files_are_read_before_source_when_budget_is_tight(tmp_path):
    """Requirements are the last thing a reviewer should lose to truncation."""
    _write_project(tmp_path)
    bundle = GitRepoGrounding().gather(
        GroundingRequest(brief="review", cwd=str(tmp_path), args={})
    )
    ordered = [i.source_id for i in bundle.items if i.source_type == "file"]
    assert ordered.index("brief.md") < ordered.index("app.py")


def test_include_arg_attaches_named_spec(tmp_path):
    _write_project(tmp_path)
    bundle = GitRepoGrounding().gather(
        GroundingRequest(brief="review", cwd=str(tmp_path), args={"include": "brief.md"})
    )
    included = [i for i in bundle.items if i.metadata.get("included") == "true"]
    assert [i.source_id for i in included] == ["brief.md"]
    assert "every SKU" in included[0].content


def test_include_does_not_suppress_the_working_tree_scan(tmp_path):
    """Attaching the spec must not cost you the code.

    First cut of this fix keyed the fallback on "any file item exists", so an
    `include=brief.md` satisfied it and the reviewer got requirements and no
    source — the mirror image of the original bug.
    """
    _write_project(tmp_path)
    bundle = GitRepoGrounding().gather(
        GroundingRequest(brief="review", cwd=str(tmp_path), args={"include": "brief.md"})
    )
    names = [i.source_id for i in bundle.items]
    assert "brief.md" in names
    assert "app.py" in names, "code must still be scanned when a spec is included"
    assert names.count("brief.md") == 1, "included file must not be read twice"


def test_include_pattern_that_matches_nothing_is_reported(tmp_path):
    _write_project(tmp_path)
    bundle = GitRepoGrounding().gather(
        GroundingRequest(brief="review", cwd=str(tmp_path), args={"include": "nope.md"})
    )
    assert any("matched nothing" in w for w in bundle.warnings)


def test_truly_empty_directory_yields_no_evidence_and_says_so(tmp_path):
    bundle = GitRepoGrounding().gather(
        GroundingRequest(brief="review", cwd=str(tmp_path), args={})
    )
    assert not bundle.has_evidence
    assert any("reviewing nothing" in w for w in bundle.warnings)


def test_vendor_directories_are_skipped(tmp_path):
    _write_project(tmp_path)
    vendor = tmp_path / "node_modules" / "pkg"
    vendor.mkdir(parents=True)
    (vendor / "index.js").write_text("module.exports = 1\n", encoding="utf-8")

    bundle = GitRepoGrounding().gather(
        GroundingRequest(brief="review", cwd=str(tmp_path), args={})
    )
    assert not any("node_modules" in (i.location or "") for i in bundle.items)


# --------------------------------------------------------------------------
# policy: an ungrounded council must not report COMPLETED
# --------------------------------------------------------------------------

def _council(policy: ExecutionPolicy):
    return SimpleNamespace(execution_policy=policy)


def _advisors(n: int):
    return [
        SimpleNamespace(
            outcome=SimpleNamespace(ok=True),
            persona=SimpleNamespace(role_id=f"role_{i}"),
        )
        for i in range(n)
    ]


def test_insufficient_grounding_fails_closed():
    policy = ExecutionPolicy(
        min_grounding_items=1,
        on_insufficient_grounding=MissingRoleBehavior.FAIL_CLOSED,
    )
    status, warnings = _apply_policy(
        _council(policy), _advisors(4), [], True, grounding_items=0
    )
    assert status == RunStatus.FAILED
    assert any("FAIL-CLOSED" in w and "reviewing nothing" in w for w in warnings)


def test_insufficient_grounding_can_degrade_instead():
    policy = ExecutionPolicy(
        min_grounding_items=2,
        on_insufficient_grounding=MissingRoleBehavior.DEGRADE_WITH_WARNING,
    )
    status, _ = _apply_policy(
        _council(policy), _advisors(4), [], True, grounding_items=1
    )
    assert status == RunStatus.DEGRADED


def test_sufficient_grounding_still_completes():
    policy = ExecutionPolicy(
        min_grounding_items=1,
        on_insufficient_grounding=MissingRoleBehavior.FAIL_CLOSED,
    )
    status, _ = _apply_policy(
        _council(policy), _advisors(4), [], True, grounding_items=3
    )
    assert status == RunStatus.COMPLETED


def test_grounding_failure_is_not_laundered_into_degraded():
    """A missing-role degrade must never soften an evidence-floor failure."""
    policy = ExecutionPolicy(
        required_successful_roles={"absent_role"},
        on_missing_required_role=MissingRoleBehavior.DEGRADE_WITH_WARNING,
        min_grounding_items=1,
        on_insufficient_grounding=MissingRoleBehavior.FAIL_CLOSED,
    )
    status, _ = _apply_policy(
        _council(policy), _advisors(4), [], True, grounding_items=0
    )
    assert status == RunStatus.FAILED


def test_unknown_grounding_count_skips_the_check():
    """grounding_items=-1 means 'not supplied' — old callers keep working."""
    policy = ExecutionPolicy(
        min_grounding_items=1,
        on_insufficient_grounding=MissingRoleBehavior.FAIL_CLOSED,
    )
    status, _ = _apply_policy(_council(policy), _advisors(4), [], True)
    assert status == RunStatus.COMPLETED


# --------------------------------------------------------------------------
# pack wiring
# --------------------------------------------------------------------------

@pytest.mark.parametrize("pack_id", ["dev", "dev_cursor"])
def test_dev_packs_declare_the_floors(pack_id):
    policy = load_pack(pack_id).execution_policy
    assert policy.min_grounding_items >= 1
    assert policy.on_insufficient_grounding == MissingRoleBehavior.FAIL_CLOSED
    assert policy.min_completed_advisors >= 3


def test_dev_run_over_empty_dir_fails_instead_of_reviewing_nothing(
    tmp_path, fake_registry
):
    """End-to-end reproduction of the incident, now failing closed."""
    req = CouncilRequest(
        brief="review this", pack="dev", mode="review", stakes="standard",
        cwd=str(tmp_path),
    )
    result, _ = run_council(
        req, registry=fake_registry, packs={"dev": load_pack("dev")}, seed=7
    )
    assert result.execution.status == RunStatus.FAILED
    assert any("reviewing nothing" in w for w in result.warnings)
    # Fail fast: no advisor should have been paid to review an empty bundle.
    assert result.advisor_results == []
    assert result.verdict is None
    stages = {s.stage: s.status for s in result.execution.stages}
    assert stages.get("dispatch") == "skipped"


def test_dev_run_over_real_files_still_completes(tmp_path, fake_registry):
    """The floor must not block a legitimate non-git review."""
    _write_project(tmp_path)
    req = CouncilRequest(
        brief="review this", pack="dev", mode="review", stakes="standard",
        cwd=str(tmp_path),
    )
    result, _ = run_council(
        req, registry=fake_registry, packs={"dev": load_pack("dev")}, seed=7
    )
    assert result.execution.status == RunStatus.COMPLETED
    assert result.grounding and result.grounding.has_evidence
