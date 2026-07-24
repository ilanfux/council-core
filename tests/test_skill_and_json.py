"""--json output and skill install (offline)."""

from __future__ import annotations

import json
from pathlib import Path

from council_core.cli import main
from council_core.format import result_to_dict
from council_core.input import CouncilRequest
from council_core.orchestrator import run_council
from council_core.pack import load_pack
from council_core.skill_install import install_skill, skill_source_dir

from conftest import FakeRegistry


def test_result_to_dict_includes_assignments():
    packs = {p: load_pack(p) for p in ("dev",)}
    result, _ = run_council(
        CouncilRequest(brief="review this PR", pack="dev", mode="review"),
        registry=FakeRegistry(),
        packs=packs,
        seed=1,
    )
    payload = result_to_dict(result)
    assert payload["convened"] is True
    assert payload["cascade_tier"] == "unchanged"
    assert payload["model_assignments"]
    assert "markdown" in payload
    assert payload["execution"]["status"] in {"completed", "degraded", "failed"}


def test_run_json_flag(monkeypatch, capsys):
    # Avoid live backends: patch run_council used by CLI.
    packs = {p: load_pack(p) for p in ("dev", "finance", "career", "dev_cursor")}

    def fake_run(request, **kwargs):
        return run_council(
            request,
            registry=FakeRegistry(),
            packs=packs,
            seed=3,
            on_assignments=kwargs.get("on_assignments"),
        )

    monkeypatch.setattr("council_core.cli.run_council", fake_run)
    monkeypatch.setattr("council_core.cli._load_all_packs", lambda config: packs)
    rc = main(
        [
            "run",
            "--pack",
            "dev",
            "--mode",
            "review",
            "--non-interactive",
            "--json",
            "review this PR",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["convened"] is True
    assert data["council"]["pack_id"] == "dev"


def test_skill_source_exists():
    src = skill_source_dir()
    assert (src / "SKILL.md").is_file()
    # Canonical path lives under the package, not repo-root duplicates.
    assert "council_core" in src.parts and "skills" in src.parts


def test_skill_install_to_temp(tmp_path):
    src = skill_source_dir()
    source_text = (src / "SKILL.md").read_text(encoding="utf-8")
    installed, notes = install_skill(
        cursor=True,
        claude=True,
        personal=False,
        project=True,
        project_root=tmp_path,
    )
    assert len(installed) == 2
    for path in installed:
        copied = path / "SKILL.md"
        assert copied.is_file()
        assert copied.read_text(encoding="utf-8") == source_text
        assert "council" in path.parts
    assert any("Restart" in n for n in notes)


def test_skill_install_cli(tmp_path, capsys):
    rc = main(
        [
            "skill",
            "install",
            "--all",
            "--project",
            "--project-root",
            str(tmp_path),
        ]
    )
    assert rc == 0
    assert (tmp_path / ".cursor" / "skills" / "council" / "SKILL.md").is_file()
    assert (tmp_path / ".claude" / "skills" / "council" / "SKILL.md").is_file()
    assert "installed ->" in capsys.readouterr().out
