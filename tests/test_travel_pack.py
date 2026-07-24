"""Travel pack load + mode membership."""

from __future__ import annotations

from council_core.pack import load_pack
from council_core.policy import MissingRoleBehavior


def test_travel_pack_loads_and_modes():
    pack = load_pack("travel")
    assert pack.id == "travel"
    assert pack.modes == ["plan", "food", "route"]
    assert pack.default_mode == "plan"
    assert pack.grounding.name == "documents"
    assert pack.output_contract.schema_id == "travel_verdict_v1"
    assert pack.execution_policy.required_successful_roles == {"risk_auditor", "fact_analyst"}
    assert pack.execution_policy.on_missing_required_role == MissingRoleBehavior.DEGRADE_WITH_WARNING
    assert pack.chairman.role_id == "chairman"
    assert "chairman" not in pack.personas

    core_keys = {k for k, p in pack.personas.items() if p.core}
    assert core_keys == {
        "itinerary_architect",
        "gastronomy_guide",
        "family_specialist",
        "risk_auditor",
        "fact_analyst",
    }
    assert pack.personas["risk_auditor"].role_id == "risk_auditor"
    assert pack.personas["fact_analyst"].role_id == "fact_analyst"

    # Mode membership: core + reservation_ops on all three; scout on plan+route only.
    for mode in ("plan", "food", "route"):
        keys = set(pack.personas_for_mode(mode))
        assert core_keys <= keys
        assert "reservation_ops" in keys
    assert "neighborhood_scout" in pack.personas_for_mode("plan")
    assert "neighborhood_scout" in pack.personas_for_mode("route")
    assert "neighborhood_scout" not in pack.personas_for_mode("food")

    # Standard = core only; thorough = full mode roster.
    assert {p.key for p in pack.personas_for_mode("plan").values() if p.core} == core_keys
    assert pack.get_tier("standard").roster == "core"
    assert pack.get_tier("thorough").roster == "full"
    assert pack.get_tier("thorough").peer_review is True


def test_travel_cursor_opt_in_and_cursor_backends():
    pack = load_pack("travel_cursor")
    assert pack.id == "travel_cursor"
    assert pack.default_backend == "cursor"
    assert pack.chairman.backend == "cursor"
    assert all(p.backend == "cursor" for p in pack.personas.values())
    families = {p.family for p in pack.personas.values() if p.core}
    assert len(families) >= 3
    assert "code" not in pack.triggers
    assert any("cursor" in t for t in pack.triggers)
    # Must not steal free `travel` routing surface with a bare "travel" trigger.
    assert "travel" not in pack.triggers
    assert pack.output_contract.schema_id == "travel_verdict_v1"
    assert "neighborhood_scout" not in pack.personas_for_mode("food")
    assert "reservation_ops" in pack.personas_for_mode("food")
