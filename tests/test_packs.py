"""Pack loading + normalization: the domain-neutral contract."""

from __future__ import annotations

import pytest

from council_core.pack import list_builtin_packs, load_pack


@pytest.mark.parametrize(
    "pid",
    ["dev", "dev_cursor", "finance", "finance_cursor", "career", "career_cursor"],
)
def test_pack_loads(pid):
    pack = load_pack(pid)
    assert pack.id == pid
    assert pack.default_mode in pack.modes
    assert pack.chairman.role_id == "chairman"
    assert pack.chairman.key == "chairman"
    # chairman is NOT one of the advisors
    assert "chairman" not in pack.personas
    for mode in pack.modes:
        assert pack.personas_for_mode(mode), f"{pid} mode {mode} empty"
    assert pack.prompt_set.versions  # templates have version hashes


def test_builtins_discovered():
    assert set(list_builtin_packs()) >= {
        "dev",
        "dev_cursor",
        "finance",
        "finance_cursor",
        "career",
        "career_cursor",
    }


def test_dev_cursor_uses_cursor_backends():
    pack = load_pack("dev_cursor")
    assert pack.default_backend == "cursor"
    assert pack.chairman.backend == "cursor"
    assert all(p.backend == "cursor" for p in pack.personas.values())
    # Diverse families across the core review roster
    review = pack.personas_for_mode("review")
    core = [p for p in review.values() if p.core]
    families = {p.family for p in core}
    assert len(families) >= 2
    # Opt-in triggers — must not steal the free `dev` pack's routing surface
    assert "code" not in pack.triggers
    assert any("cursor" in t for t in pack.triggers)

def test_finance_mandatory_roles_and_failclosed():
    pack = load_pack("finance")
    role_ids = {p.role_id for p in pack.personas.values() if p.role_id}
    assert {"fact_analyst", "risk_auditor"} <= role_ids
    assert pack.execution_policy.required_successful_roles == {"fact_analyst", "risk_auditor"}
    assert pack.execution_policy.on_missing_required_role.value == "fail_closed"


def test_dev_has_no_required_roles():
    pack = load_pack("dev")
    assert pack.execution_policy.required_successful_roles == set()


def test_persona_prompt_accepts_lens_or_system_prompt():
    dev = load_pack("dev")
    assert dev.personas["bug_hunter"].prompt  # from `lens:`
    fin = load_pack("finance")
    assert fin.personas["risk_auditor"].prompt  # from `prompt:`
