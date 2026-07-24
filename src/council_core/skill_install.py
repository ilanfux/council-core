"""Install the council skill into Cursor and/or Claude Code skill directories."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import List, Optional, Tuple

SKILL_NAME = "council"


def skill_source_dir() -> Path:
    """Prefer repo ``skills/council``; fall back to the packaged copy."""

    # council_core/ -> src/ -> repo root (editable / source checkout)
    repo_root = Path(__file__).resolve().parents[2]
    repo_skill = repo_root / "skills" / SKILL_NAME
    if (repo_skill / "SKILL.md").is_file():
        return repo_skill
    bundled = Path(__file__).resolve().parent / "skills" / SKILL_NAME
    if (bundled / "SKILL.md").is_file():
        return bundled
    raise FileNotFoundError(
        "Skill source missing (looked in repo skills/council and package "
        "council_core/skills/council)."
    )

def install_targets(
    *,
    cursor: bool = True,
    claude: bool = True,
    personal: bool = True,
    project: bool = False,
    project_root: Optional[Path] = None,
) -> List[Path]:
    """Return destination skill directories (parent that will contain SKILL.md)."""

    home = Path.home()
    targets: List[Path] = []
    if personal and cursor:
        targets.append(home / ".cursor" / "skills" / SKILL_NAME)
    if personal and claude:
        targets.append(home / ".claude" / "skills" / SKILL_NAME)
    if project:
        root = (project_root or Path.cwd()).resolve()
        if cursor:
            targets.append(root / ".cursor" / "skills" / SKILL_NAME)
        if claude:
            targets.append(root / ".claude" / "skills" / SKILL_NAME)
    return targets


def install_skill(
    *,
    cursor: bool = True,
    claude: bool = True,
    personal: bool = True,
    project: bool = False,
    project_root: Optional[Path] = None,
    source: Optional[Path] = None,
) -> Tuple[List[Path], List[str]]:
    """Copy the skill into assistant skill dirs. Returns (installed_paths, notes)."""

    src = source or skill_source_dir()
    skill_md = src / "SKILL.md"
    if not skill_md.is_file():
        raise FileNotFoundError(
            f"Skill source missing: {skill_md}. Expected skills/council/SKILL.md in the repo."
        )

    notes: List[str] = []
    installed: List[Path] = []
    for dest in install_targets(
        cursor=cursor,
        claude=claude,
        personal=personal,
        project=project,
        project_root=project_root,
    ):
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
        installed.append(dest)
        notes.append(f"installed -> {dest}")

    if not installed:
        notes.append("no targets selected (pass --cursor/--claude and --personal/--project)")
    else:
        notes.append(
            "Restart Cursor / Claude Code (or start a new agent chat) so the skill is discovered."
        )
    return installed, notes


def describe_manual_steps() -> str:
    src = skill_source_dir()
    return (
        "Manual install (if you prefer not to run `council skill install`):\n"
        f"  Cursor personal:  copy {src} -> ~/.cursor/skills/council/\n"
        f"  Claude personal:  copy {src} -> ~/.claude/skills/council/\n"
        "  Cursor project:   copy -> <repo>/.cursor/skills/council/\n"
        "  Claude project:   copy -> <repo>/.claude/skills/council/\n"
        "Then restart the assistant so it reloads skills."
    )
