"""Unit tests for sdk_client helpers and the model-resolve cascade (no network)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from council_core.config_loader import RuntimeConfig
from council_core.grounding import NullGrounding
from council_core.input import CouncilRequest, PersonaSpec
from council_core.model_resolve import (
    cursor_needed_for,
    resolve_council_models,
    resolve_cursor_models,
    validate_model_params,
)
from council_core.output import builtin_contract
from council_core.persona_architect import ModelAssignment
from council_core.policy import ExecutionPolicy
from council_core.prompts import PromptSet
from council_core.sdk_client import SdkUnavailableError, build_model_selection
from council_core.spec import CouncilSpec

from conftest import FakeRegistry


def _persona(key: str, backend: str, model: str, family: str = "", **kwargs) -> PersonaSpec:
    return PersonaSpec(
        key=key,
        title=key.replace("_", " ").title(),
        prompt="lens",
        model=model,
        family=family or backend,
        backend=backend,
        core=True,
        **kwargs,
    )


def _council(*advisors: PersonaSpec, chairman: PersonaSpec | None = None, **kwargs) -> CouncilSpec:
    chair = chairman or _persona("chairman", "google", "gemini-2.5-flash", role_id="chairman")
    return CouncilSpec(
        origin="pack",
        pack_id="test",
        mode="review",
        stakes="standard",
        advisors=list(advisors),
        chairman=chair,
        prompt_set=PromptSet.load(None),
        grounding=NullGrounding(),
        output_contract=builtin_contract("generic_verdict_v1"),
        execution_policy=ExecutionPolicy(),
        peer_review=False,
        default_model=kwargs.pop("default_model", "gpt-5.5"),
        **kwargs,
    )


# ----- sdk_client ----------------------------------------------------------- #


def test_build_model_selection_plain_id():
    assert build_model_selection("gpt-5.5") == "gpt-5.5"
    assert build_model_selection("gpt-5.5", {}) == "gpt-5.5"


def test_build_model_selection_with_params():
    sel = build_model_selection("gpt-5.5", {"reasoning": "high"})
    assert sel == {"id": "gpt-5.5", "params": [{"id": "reasoning", "value": "high"}]}


def test_sdk_unavailable_is_backend_error():
    from council_core.backends.base import BackendError

    assert issubclass(SdkUnavailableError, BackendError)


# ----- gate ----------------------------------------------------------------- #


def test_cursor_needed_false_for_provider_pack():
    council = _council(
        _persona("a", "google", "gemini-2.5-flash"),
        _persona("b", "groq", "llama-3.3-70b-versatile", family="groq"),
    )
    assert cursor_needed_for(council) is False


def test_cursor_needed_true_for_cursor_advisor():
    council = _council(_persona("a", "cursor", "gpt-5.5", family="openai"))
    assert cursor_needed_for(council) is True


def test_cursor_needed_true_for_cursor_chairman():
    council = _council(
        _persona("a", "google", "gemini-2.5-flash"),
        chairman=_persona("chairman", "cursor", "claude-sonnet-4-6", family="anthropic"),
    )
    assert cursor_needed_for(council) is True


# ----- Priority A: Cursor catalog ------------------------------------------- #


def test_resolve_cursor_models_falls_back_unknown_slug():
    council = _council(
        _persona("hunter", "cursor", "does-not-exist", family="openai",
                 model_params={"reasoning": "high"}),
        chairman=_persona("chairman", "cursor", "gpt-5.5", family="openai"),
        default_model="gpt-5.5",
    )
    warnings = resolve_cursor_models(council, ["gpt-5.5", "claude-sonnet-4-6"])
    assert council.advisors[0].model == "gpt-5.5"
    assert council.advisors[0].model_params == {}  # dropped on family-crossing fallback
    assert any("does-not-exist" in w for w in warnings)


def test_resolve_cursor_models_empty_catalog_no_rewrite():
    council = _council(_persona("hunter", "cursor", "gpt-5.5", family="openai"))
    warnings = resolve_cursor_models(council, [])
    assert warnings == []
    assert council.advisors[0].model == "gpt-5.5"


def test_validate_model_params_drops_unsupported():
    council = _council(
        _persona(
            "hunter",
            "cursor",
            "gpt-5.5",
            family="openai",
            model_params={"reasoning": "high", "effort": "xhigh"},
        ),
        chairman=_persona("chairman", "google", "gemini-2.5-flash"),
    )
    catalog = {"gpt-5.5": {"reasoning": {"high", "medium", "low"}}}
    warnings = validate_model_params(council, catalog)
    assert council.advisors[0].model_params == {"reasoning": "high"}
    assert any("effort" in w for w in warnings)


# ----- Cascade A → B → C ---------------------------------------------------- #


def test_provider_pack_unchanged_no_discover_call():
    calls = {"n": 0}

    def discover(_key):
        calls["n"] += 1
        return ["gpt-5.5"], {}

    council = _council(_persona("a", "google", "gemini-2.5-flash"))
    # Keep a reference to the original persona object to prove we copy on resolve.
    original = council.advisors[0]
    cfg = RuntimeConfig(backends={}, dynamic_pool=[])
    result = resolve_council_models(
        council, cfg, FakeRegistry(), discover=discover
    )
    assert result.tier == "unchanged"
    assert calls["n"] == 0
    # Copies were made even for unchanged tier (safe mutation boundary).
    assert council.advisors[0] is not original
    assert council.advisors[0].model == "gemini-2.5-flash"


def test_cascade_to_providers_when_cursor_unavailable():
    def discover(_key):
        raise SdkUnavailableError("no key")

    council = _council(
        _persona("hunter", "cursor", "gpt-5.5", family="openai"),
        chairman=_persona("chairman", "cursor", "claude-opus-4-8", family="anthropic"),
    )
    cfg = RuntimeConfig(
        backends={"google": {"type": "google"}, "groq": {"type": "openai"}},
        dynamic_pool=[
            {"backend": "google", "model": "gemini-2.5-flash", "family": "google"},
            {"backend": "groq", "model": "llama-3.3-70b-versatile", "family": "groq"},
        ],
    )
    result = resolve_council_models(
        council, cfg, FakeRegistry(), discover=discover
    )
    assert result.tier == "providers"
    assert council.chairman.backend == "google"  # round-robin first
    assert council.advisors[0].backend == "groq"
    assert any("cascading to configured provider" in w.lower() for w in result.warnings)
    summary = result.summary_text()
    assert "hunter" in summary.lower() or "Hunter" in summary
    assert "gemini-2.5-flash" in summary


def test_cascade_to_ui_when_no_providers():
    def discover(_key):
        raise SdkUnavailableError("no sdk")

    council = _council(_persona("hunter", "cursor", "gpt-5.5", family="openai"))
    cfg = RuntimeConfig(backends={}, dynamic_pool=[])
    result = resolve_council_models(
        council,
        cfg,
        FakeRegistry(),
        discover=discover,
        ui_model="composer-2.5",
        ui_backend="cursor",
    )
    assert result.tier == "ui"
    assert all(p.backend == "cursor" and p.model == "composer-2.5" for p in council.advisors)
    assert council.chairman.model == "composer-2.5"


def test_cascade_cursor_success_keeps_diverse_models():
    def discover(_key):
        return (
            ["gpt-5.5", "claude-sonnet-4-6", "composer-2.5", "gemini-3.1-pro"],
            {
                "gpt-5.5": {"reasoning": {"high", "low"}},
                "claude-sonnet-4-6": {"effort": {"high", "xhigh"}, "thinking": {"true", "false"}},
            },
        )

    council = _council(
        _persona("hunter", "cursor", "gpt-5.5", family="openai",
                 model_params={"reasoning": "high"}),
        _persona("maint", "cursor", "composer-2.5", family="cursor"),
        chairman=_persona("chairman", "cursor", "claude-sonnet-4-6", family="anthropic",
                          model_params={"effort": "high", "thinking": "true"}),
        default_model="gpt-5.5",
    )
    cfg = RuntimeConfig(backends={}, dynamic_pool=[])
    result = resolve_council_models(
        council, cfg, FakeRegistry(), discover=discover
    )
    assert result.tier == "cursor"
    assert council.advisors[0].model == "gpt-5.5"
    assert council.advisors[1].model == "composer-2.5"
    assert council.chairman.model == "claude-sonnet-4-6"


def test_orchestrator_announces_assignments(packs=None):
    from council_core.orchestrator import run_council
    from council_core.pack import load_pack

    packs = {p: load_pack(p) for p in ("dev", "finance", "career")}
    announced: list[str] = []
    req = CouncilRequest(brief="review this PR", pack="dev", mode="review", stakes="standard")
    result, _ = run_council(
        req,
        registry=FakeRegistry(),
        packs=packs,
        seed=7,
        on_assignments=announced.append,
    )
    assert result.convened
    assert result.cascade_tier == "unchanged"
    assert announced and "Model assignments" in announced[0]
    assert result.model_assignments
