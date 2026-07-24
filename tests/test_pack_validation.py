"""Failure-path coverage for pack loading/validation (dev-council round C)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from council_core.pack import PackError, load_pack


def _write_pack(tmp: Path, personas_yaml: str, pack_yaml: str | None = None) -> Path:
    (tmp / "pack.yaml").write_text(
        pack_yaml
        or textwrap.dedent(
            """
            schema_version: 1
            id: t
            council: { personas_file: personas.yaml }
            grounding: { provider: "null" }
            output: { schema: generic_verdict_v1 }
            """
        ),
        encoding="utf-8",
    )
    (tmp / "personas.yaml").write_text(textwrap.dedent(personas_yaml), encoding="utf-8")
    return tmp


def test_non_dict_persona_raises(tmp_path: Path):
    _write_pack(tmp_path, """
        default_model: m
        modes: [advise]
        chairman: { title: C, model: m, family: f }
        personas:
          bad: "i am a string not a mapping"
    """)
    with pytest.raises(PackError, match="must be a mapping"):
        load_pack(str(tmp_path))


def test_chairman_without_model_raises(tmp_path: Path):
    _write_pack(tmp_path, """
        modes: [advise]
        chairman: { title: C, family: f }
        personas:
          a: { title: A, model: m, family: f, prompt: x }
    """)
    with pytest.raises(PackError, match="chairman has no model"):
        load_pack(str(tmp_path))


def test_malformed_yaml_wrapped_in_packerror(tmp_path: Path):
    (tmp_path / "pack.yaml").write_text(
        "schema_version: 1\nid: t\ncouncil: { personas_file: personas.yaml }\n", encoding="utf-8"
    )
    (tmp_path / "personas.yaml").write_text("this: : : not valid yaml\n  - broken", encoding="utf-8")
    with pytest.raises(PackError):
        load_pack(str(tmp_path))


def test_unknown_grounding_wrapped(tmp_path: Path):
    pack_yaml = textwrap.dedent(
        """
        schema_version: 1
        id: t
        council: { personas_file: personas.yaml }
        grounding: { provider: does_not_exist }
        output: { schema: generic_verdict_v1 }
        """
    )
    _write_pack(tmp_path, """
        modes: [advise]
        chairman: { title: C, model: m, family: f }
        personas:
          a: { title: A, model: m, family: f, prompt: x }
    """, pack_yaml=pack_yaml)
    with pytest.raises(PackError):
        load_pack(str(tmp_path))


def test_manifest_file_escape_rejected(tmp_path: Path):
    pack_yaml = textwrap.dedent(
        """
        schema_version: 1
        id: t
        council: { personas_file: ../evil.yaml }
        grounding: { provider: "null" }
        output: { schema: generic_verdict_v1 }
        """
    )
    (tmp_path / "pack.yaml").write_text(pack_yaml, encoding="utf-8")
    (tmp_path.parent / "evil.yaml").write_text("modes: [advise]\n", encoding="utf-8")
    with pytest.raises(PackError, match="escapes the pack directory"):
        load_pack(str(tmp_path))


@pytest.mark.parametrize("pid", ["dev", "finance", "career", "travel", "travel_cursor"])
def test_builtin_packs_still_valid(pid):
    load_pack(pid)  # must not raise after all the new validation
