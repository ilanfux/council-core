"""Grounding adapters, output contracts, and manifest serialization."""

from __future__ import annotations

from pathlib import Path

from council_core.grounding import (
    DocumentGrounding,
    GroundingRequest,
    NullGrounding,
    get_grounding,
)
from council_core.output import builtin_contract


def test_null_grounding_is_honest():
    bundle = NullGrounding().gather(GroundingRequest(brief="x"))
    assert not bundle.has_evidence
    assert bundle.warnings
    assert "no external evidence" in bundle.render().lower()


def test_document_grounding_reads_text(tmp_path: Path):
    doc = tmp_path / "payslip.md"
    doc.write_text("Gross salary: 20000 NIS\n", encoding="utf-8")
    bundle = DocumentGrounding().gather(
        GroundingRequest(brief="x", cwd=str(tmp_path), args={"documents": f"Payslip::{doc}"})
    )
    assert bundle.has_evidence
    item = bundle.items[0]
    assert item.source_type == "document" and item.title == "Payslip"
    assert "20000" in item.content


def test_document_grounding_missing_file_warns(tmp_path: Path):
    bundle = DocumentGrounding().gather(
        GroundingRequest(brief="x", cwd=str(tmp_path), args={"documents": "nope.md"})
    )
    assert not bundle.has_evidence
    assert any("not found" in w for w in bundle.warnings)


def test_get_grounding_unknown():
    try:
        get_grounding("does_not_exist")
        assert False
    except ValueError:
        pass


def test_output_contract_validation():
    contract = builtin_contract("finance_brief_v1")
    ok = contract.validate("### Recommended action\n### Risks and irreversibility\n### One concrete next action")
    assert ok == []
    bad = contract.validate("just some text")
    assert bad  # missing required sections
