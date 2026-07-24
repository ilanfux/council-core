"""Document visibility to grounded backends (a' loud banner)."""

from __future__ import annotations

from pathlib import Path

from council_core.format import render_markdown
from council_core.grounding.bundle import EvidenceItem, GroundingBundle, GroundingRequest
from council_core.grounding.documents import DocumentGrounding
from council_core.grounding.null import NullGrounding
from council_core.grounding.visibility import (
    format_invisible_docs_banner,
    invisible_document_locations,
    path_under_cwd,
)
from council_core.input import CouncilRequest, PersonaSpec
from council_core.orchestrator import run_council
from council_core.output import builtin_contract
from council_core.pack import load_pack
from council_core.policy import ExecutionPolicy, RunStatus
from council_core.prompts import PromptSet
from council_core.result import CouncilResult, ExecutionSummary
from council_core.router import RouteDecision
from council_core.spec import CouncilSpec

from conftest import FakeBackend


class _SelectiveRegistry:
    """Cursor = grounded; everything else = not."""

    def __init__(self) -> None:
        self._cursor = FakeBackend()
        self._cursor.name = "cursor"
        self._cursor.grounded = True
        self._provider = FakeBackend()
        self._provider.name = "google"
        self._provider.grounded = False

    def get(self, name: str) -> FakeBackend:
        return self._cursor if name == "cursor" else self._provider


def _persona(key: str, backend: str = "cursor", model: str = "gpt-5.5") -> PersonaSpec:
    return PersonaSpec(
        key=key,
        title=key.title(),
        prompt="lens",
        model=model,
        family="openai",
        capability="medium",
        backend=backend,
        role_id=key if key in {"risk_auditor", "fact_analyst"} else None,
    )


def _spec(*, advisors=None, chairman=None, grounding=None) -> CouncilSpec:
    return CouncilSpec(
        pack_id="travel_cursor",
        origin="pack",
        mode="plan",
        stakes="standard",
        advisors=advisors or [_persona("itinerary_architect")],
        chairman=chairman or _persona("chairman"),
        grounding=grounding or DocumentGrounding(),
        prompt_set=PromptSet.load(None),
        output_contract=builtin_contract("generic_verdict_v1"),
        execution_policy=ExecutionPolicy(),
        peer_review=False,
        default_model="gpt-5.5",
    )


def test_path_under_cwd(tmp_path: Path):
    inside = tmp_path / "notes.md"
    inside.write_text("hi", encoding="utf-8")
    assert path_under_cwd(str(inside), str(tmp_path))
    outside = tmp_path.parent / f"outside-{tmp_path.name}-notes.md"
    outside.write_text("x", encoding="utf-8")
    try:
        assert not path_under_cwd(str(outside), str(tmp_path))
    finally:
        outside.unlink(missing_ok=True)


def test_invisible_requires_grounded_and_documents_provider(tmp_path: Path):
    outside = tmp_path.parent / f"diet-{tmp_path.name}.md"
    outside.write_text("no peanuts", encoding="utf-8")
    try:
        bundle = DocumentGrounding().gather(
            GroundingRequest(
                brief="trip",
                cwd=str(tmp_path),
                args={"documents": f"diet::{outside}"},
            )
        )
        council = _spec()
        reg = _SelectiveRegistry()
        locs = invisible_document_locations(
            bundle=bundle, cwd=str(tmp_path), council=council, registry=reg
        )
        assert locs and Path(locs[0]).name.startswith("diet-")

        council.advisors[0].backend = "google"
        council.chairman.backend = "google"
        assert (
            invisible_document_locations(
                bundle=bundle, cwd=str(tmp_path), council=council, registry=reg
            )
            == []
        )

        council.advisors[0].backend = "cursor"
        council.chairman.backend = "cursor"
        council.grounding = NullGrounding()
        assert (
            invisible_document_locations(
                bundle=bundle, cwd=str(tmp_path), council=council, registry=reg
            )
            == []
        )
    finally:
        outside.unlink(missing_ok=True)


def test_banner_names_basenames():
    text = format_invisible_docs_banner([r"C:\trips\notes.md", r"C:\trips\ages.txt"])
    assert "2 documents" in text
    assert "notes.md" in text and "ages.txt" in text
    assert "place under --cwd" in text


def test_markdown_banner_is_top_level():
    result = CouncilResult(
        convened=True,
        route=RouteDecision(kind="pack", selected_pack="travel_cursor", confidence=1.0, reason="t"),
        council=_spec(),
        grounding=GroundingBundle(
            items=(
                EvidenceItem(
                    source_id="notes.md",
                    source_type="document",
                    content="x",
                    location=r"D:\elsewhere\notes.md",
                ),
            )
        ),
        advisor_results=[],
        peer_reviews=[],
        verdict=None,
        execution=ExecutionSummary(status=RunStatus.COMPLETED),
        unreachable_grounding_docs=[r"D:\elsewhere\notes.md"],
    )
    md = render_markdown(result)
    assert "> WARNING: 1 document not visible to grounded Cursor agents" in md
    assert "notes.md" in md


_CURSOR_MODELS = [
    "gpt-5.5",
    "gpt-5.4",
    "claude-sonnet-4-6",
    "claude-opus-4-8",
    "gemini-3.1-pro",
    "composer-2.5",
]


def test_orchestrator_warns_when_cursor_docs_outside_cwd(tmp_path: Path, monkeypatch):
    from council_core import model_resolve as mr

    packs = {"travel_cursor": load_pack("travel_cursor")}
    outside = tmp_path.parent / f"itinerary-{tmp_path.name}.md"
    outside.write_text("Day 1: leave early", encoding="utf-8")

    monkeypatch.setattr(mr, "discover_models", lambda _key=None: (_CURSOR_MODELS, {}))
    try:
        req = CouncilRequest(
            brief="plan a 5-day family driving trip",
            pack="travel_cursor",
            mode="plan",
            stakes="standard",
            cwd=str(tmp_path),
            grounding_args={"documents": f"draft::{outside}"},
        )
        result, _ = run_council(req, registry=_SelectiveRegistry(), packs=packs, seed=3)
    finally:
        outside.unlink(missing_ok=True)

    assert result.convened
    assert result.cascade_tier == "cursor"
    assert result.unreachable_grounding_docs
    # Dedicated field only — must not also land in warnings (would double-render).
    assert not any("not visible to grounded Cursor agents" in w for w in result.warnings)
    md = render_markdown(result)
    assert md.count("not visible to grounded Cursor agents") == 1
    assert "itinerary-" in md


def test_orchestrator_no_warn_after_cascade_to_providers(tmp_path: Path, monkeypatch):
    from council_core import model_resolve as mr
    from council_core.config_loader import RuntimeConfig
    from council_core.sdk_client import SdkUnavailableError

    packs = {"travel_cursor": load_pack("travel_cursor")}
    outside = tmp_path.parent / f"notes-{tmp_path.name}.md"
    outside.write_text("ages: 14, 12, 8", encoding="utf-8")

    def boom(_key=None):
        raise SdkUnavailableError("no key")

    monkeypatch.setattr(mr, "discover_models", boom)
    cfg = RuntimeConfig(
        backends={"google": {"type": "google"}, "groq": {"type": "openai"}},
        dynamic_pool=[
            {"backend": "google", "model": "gemini-2.5-flash", "family": "google"},
            {"backend": "groq", "model": "llama-3.3-70b-versatile", "family": "groq"},
        ],
    )
    try:
        req = CouncilRequest(
            brief="food-heavy weekend",
            pack="travel_cursor",
            mode="food",
            stakes="standard",
            cwd=str(tmp_path),
            grounding_args={"documents": f"notes::{outside}"},
        )
        result, _ = run_council(
            req, config=cfg, registry=_SelectiveRegistry(), packs=packs, seed=3
        )
    finally:
        outside.unlink(missing_ok=True)

    assert result.convened
    assert result.cascade_tier == "providers"
    assert result.unreachable_grounding_docs == []
    assert not any("not visible to grounded Cursor agents" in w for w in result.warnings)


def test_orchestrator_no_warn_when_docs_under_cwd(tmp_path: Path, monkeypatch):
    from council_core import model_resolve as mr

    packs = {"travel_cursor": load_pack("travel_cursor")}
    inside = tmp_path / "constraints.md"
    inside.write_text("no shellfish", encoding="utf-8")

    monkeypatch.setattr(mr, "discover_models", lambda _key=None: (_CURSOR_MODELS, {}))
    req = CouncilRequest(
        brief="route redesign",
        pack="travel_cursor",
        mode="route",
        stakes="standard",
        cwd=str(tmp_path),
        grounding_args={"documents": f"constraints::{inside}"},
    )
    result, _ = run_council(req, registry=_SelectiveRegistry(), packs=packs, seed=3)
    assert result.convened
    assert result.unreachable_grounding_docs == []
