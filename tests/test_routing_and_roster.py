"""Deterministic routing + pack roster selection."""

from __future__ import annotations

import pytest

from council_core.input import CouncilRequest
from council_core.pack import load_pack
from council_core.roster import build_pack_council
from council_core.router import Router


@pytest.fixture
def packs():
    return {p: load_pack(p) for p in ("dev", "finance", "career")}


def test_route_dev(packs):
    d = Router().route(CouncilRequest(brief="please review this PR, possible N+1 in the query loop"), packs)
    assert d.kind == "pack" and d.selected_pack == "dev"


def test_route_finance(packs):
    d = Router().route(CouncilRequest(brief="should I withdraw keren hishtalmut after termination and form 161"), packs)
    assert d.kind == "pack" and d.selected_pack == "finance"


def test_route_unknown_is_choice_required(packs):
    d = Router().route(CouncilRequest(brief="what wine pairs with grilled fish"), packs)
    assert d.kind == "choice_required" and d.confidence == 0.0


def test_explicit_pack_overrides_scoring(packs):
    d = Router().route(CouncilRequest(brief="anything", pack="career"), packs)
    assert d.kind == "pack" and d.selected_pack == "career"


def test_forced_dynamic(packs):
    d = Router().route(CouncilRequest(brief="anything", dynamic=True), packs)
    assert d.kind == "dynamic"


def test_core_vs_full_roster():
    pack = load_pack("dev")
    core = build_pack_council(pack, CouncilRequest(brief="x", mode="review", stakes="standard"))
    full = build_pack_council(pack, CouncilRequest(brief="x", mode="review", stakes="thorough"))
    assert all(p.core for p in core.advisors)
    assert len(full.advisors) > len(core.advisors)
    assert full.peer_review is True and core.peer_review is False
    # chairman is separate in both
    assert core.chairman.key == "chairman"
    assert "chairman" not in {p.key for p in core.advisors}


def test_explicit_roster_and_skipped():
    pack = load_pack("dev")
    spec = build_pack_council(
        pack, CouncilRequest(brief="x", mode="review", stakes="thorough", roster=["bug_hunter", "security"])
    )
    assert [p.key for p in spec.advisors] == ["bug_hunter", "security"]
    assert "maintainability" in spec.skipped
