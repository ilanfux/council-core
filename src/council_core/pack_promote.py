"""Draft-only pack promotion from a RunManifest.

Produces a reviewable draft pack directory. Never auto-installs into builtin or
trusted user packs — humans must validate and move deliberately.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Union

import yaml

from council_core.manifest import RunManifest
from council_core.pack import PackError, load_pack

DRAFT_MARKER = "DRAFT — not trusted until human review"


def load_manifest(source: Union[str, Path]) -> RunManifest:
    """Load a RunManifest from a JSON file path or a run_id under ~/.council/runs/."""

    path = Path(source)
    if path.is_file():
        return RunManifest.model_validate_json(path.read_text(encoding="utf-8"))

    # run-id lookup
    candidates = [
        Path.home() / ".council" / "runs" / f"{source}.json",
        Path.home() / ".council" / "manifests" / f"{source}.json",
        Path.cwd() / f"{source}.json",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return RunManifest.model_validate_json(candidate.read_text(encoding="utf-8"))
    raise PackError(
        f"manifest not found for '{source}'. Pass a JSON path from --manifest, "
        f"or place it at ~/.council/runs/<run-id>.json."
    )


def draft_pack_from_manifest(
    manifest: RunManifest,
    dest_dir: Union[str, Path],
    *,
    pack_id: Optional[str] = None,
) -> Path:
    """Write a draft pack directory. Returns the destination path."""

    dest = Path(dest_dir)
    if dest.exists() and any(dest.iterdir()):
        raise PackError(f"destination is not empty: {dest}")
    dest.mkdir(parents=True, exist_ok=True)

    pid = pack_id or f"draft_{manifest.pack_id or 'dynamic'}_{manifest.run_id[:8]}"
    pid = "".join(c if c.isalnum() or c in "-_" else "_" for c in pid).strip("_") or "draft_pack"

    if not manifest.advisors or manifest.chairman is None:
        raise PackError("manifest has no advisors/chairman to promote")

    personas = {
        a.key: {
            "title": a.title,
            "core": True,
            "backend": a.backend,
            "model": a.model,
            "family": a.family,
            **({"role_id": a.role_id} if a.role_id else {}),
            "prompt": (
                f"(DRAFT from run {manifest.run_id}) Specialize as {a.title}. "
                "Replace this placeholder prompt after human review."
            ),
        }
        for a in manifest.advisors
    }
    chairman = {
        "title": manifest.chairman.title,
        "backend": manifest.chairman.backend,
        "model": manifest.chairman.model,
        "family": manifest.chairman.family,
        "prompt": (
            f"(DRAFT from run {manifest.run_id}) Synthesize advisors into one decisive verdict. "
            "Replace this placeholder after human review."
        ),
    }

    personas_doc = {
        "default_backend": manifest.chairman.backend,
        "default_model": manifest.chairman.model,
        "modes": [manifest.mode or "default"],
        "peer_review_backend": manifest.chairman.backend,
        "peer_review_backends": {manifest.chairman.family: manifest.chairman.backend},
        "peer_review_pool": {manifest.chairman.family: manifest.chairman.model},
        "chairman": chairman,
        "personas": personas,
    }

    pack_yaml = {
        "schema_version": 1,
        "id": pid,
        "version": "0.0.1-draft",
        "display_name": f"{DRAFT_MARKER}: {pid}",
        "routing": {"triggers": []},
        "council": {"personas_file": "personas.yaml"},
        "prompts": {"directory": "prompts"},
        "grounding": {"provider": manifest.grounding_provider or "null"},
        "output": {"schema": manifest.output_schema or "generic_verdict_v1"},
        "execution": {"policy_file": "execution.yaml"},
    }

    execution = {
        "required_successful_roles": [],
        "on_missing_required_role": "degrade_with_warning",
        "min_completed_advisors": 1,
        "allow_same_family_fallback": True,
        "chairman_when_required_analysis_missing": "synthesize_with_gap_note",
    }

    (dest / "pack.yaml").write_text(yaml.safe_dump(pack_yaml, sort_keys=False), encoding="utf-8")
    (dest / "personas.yaml").write_text(
        yaml.safe_dump(personas_doc, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    (dest / "execution.yaml").write_text(yaml.safe_dump(execution, sort_keys=False), encoding="utf-8")
    prompts = dest / "prompts"
    prompts.mkdir(exist_ok=True)
    (prompts / "advisor.txt").write_text(
        "You are the {title} on a draft council.\n\nYour lens: {prompt}\n\n"
        "Brief:\n---\n{brief}\n---\n\n{grounding}\n\nRules:\n{read_rule}\n{extra}\n",
        encoding="utf-8",
    )
    provenance = {
        "status": "draft",
        "source_run_id": manifest.run_id,
        "source_pack_id": manifest.pack_id,
        "source_origin": manifest.origin,
        "architect_raw_output": manifest.architect_raw_output,
        "roster_repairs": [r.model_dump() for r in manifest.roster_repairs],
        "note": DRAFT_MARKER,
    }
    (dest / "PROVENANCE.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    (dest / "README.md").write_text(
        f"# {pid}\n\n{DRAFT_MARKER}\n\n"
        f"Promoted from run `{manifest.run_id}` (origin={manifest.origin}, "
        f"pack={manifest.pack_id}, mode={manifest.mode}).\n\n"
        "Next steps:\n"
        "1. Replace placeholder prompts in `personas.yaml`.\n"
        "2. Add routing triggers in `pack.yaml`.\n"
        "3. Run `council pack validate <this-dir>`.\n"
        "4. Only then copy into `~/.council/packs/` or builtin_packs.\n",
        encoding="utf-8",
    )
    return dest


def validate_draft_pack(path: Union[str, Path]) -> str:
    """Load+validate a pack dir; returns a short status string."""

    pack = load_pack("", pack_path=str(path))
    marker = ""
    readme = Path(path) / "README.md"
    if readme.is_file() and "DRAFT" in readme.read_text(encoding="utf-8"):
        marker = " (still marked DRAFT)"
    return (
        f"OK: pack '{pack.id}' v{pack.version} — {len(pack.personas)} advisors, "
        f"modes={pack.modes}, grounding={pack.grounding.name}{marker}"
    )
