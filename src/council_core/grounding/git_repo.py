"""Git-repository grounding (dev pack).

Snapshots the change under review (diff + tree) so non-grounded provider backends
can still cite ``path:line``. Bounded so a provider context window is never blown.
Ported from the donor's ``context.py`` into the typed grounding model.
"""

from __future__ import annotations

import subprocess
from typing import List, Optional

from council_core.grounding.bundle import (
    EvidenceItem,
    GroundingBundle,
    GroundingRequest,
    estimate_tokens,
)

_MAX_DIFF_CHARS = 60_000
_MAX_TREE_LINES = 200


def _run_git(args: List[str], cwd: str) -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit] + f"\n... [truncated, {len(text) - limit} more chars] ...", True


class GitRepoGrounding:
    name = "git_repo"

    def gather(self, request: GroundingRequest) -> GroundingBundle:
        cwd = request.cwd or "."
        diff_scope = request.args.get("diff_scope") if request.args else None

        items: List[EvidenceItem] = []
        warnings: List[str] = []
        truncated = False

        diff_args = ["diff", "--stat", "-p"]
        if diff_scope:
            diff_args.append(diff_scope)
        diff = _run_git(diff_args, cwd)
        if not diff or not diff.strip():
            # Fall back to staged, then last-commit, so a review always has context.
            diff = _run_git(["diff", "--cached", "--stat", "-p"], cwd) or _run_git(
                ["show", "--stat", "-p", "HEAD"], cwd
            )
        if diff and diff.strip():
            body, was_cut = _truncate(diff.strip(), _MAX_DIFF_CHARS)
            truncated = truncated or was_cut
            items.append(
                EvidenceItem(
                    source_id="git_diff",
                    source_type="git_diff",
                    title="Change under review (git diff)",
                    content=body,
                    location=diff_scope or "working tree",
                )
            )
        else:
            warnings.append("No git diff available (no changes, staged content, or HEAD).")

        tree = _run_git(["ls-files"], cwd)
        if tree and tree.strip():
            lines = tree.strip().splitlines()
            shown = lines[:_MAX_TREE_LINES]
            if len(lines) > _MAX_TREE_LINES:
                truncated = True
                shown.append(f"... [{len(lines) - _MAX_TREE_LINES} more files] ...")
            items.append(
                EvidenceItem(
                    source_id="git_tree",
                    source_type="file_tree",
                    title="Repository file tree",
                    content="\n".join(shown),
                )
            )

        rendered = "\n\n".join(i.content for i in items)
        return GroundingBundle(
            items=tuple(items),
            warnings=tuple(warnings),
            token_estimate=estimate_tokens(rendered),
            truncated=truncated,
        )
