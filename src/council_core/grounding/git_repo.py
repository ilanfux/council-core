"""Git-repository grounding (dev pack).

Snapshots the change under review (diff + tree) so non-grounded provider backends
can still cite ``path:line``. Bounded so a provider context window is never blown.
Ported from the donor's ``context.py`` into the typed grounding model.

Two failure modes this provider must not have, both learned the hard way:

* **Not a git repo.** A directory with no ``.git`` used to yield an empty bundle
  and the review proceeded anyway — advisors then invent generic findings because
  they are reasoning about a description, not the code. A working-tree scan is
  used as a fallback so a review always has something real to read.
* **No specification.** A reviewer holding only the diff can find style problems
  but can never find "this violates the requirement", because the requirement is
  not in front of it. ``include=`` attaches spec/brief files explicitly.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Iterable, List, Optional, Set

from council_core.grounding.bundle import (
    EvidenceItem,
    GroundingBundle,
    GroundingRequest,
    estimate_tokens,
)

_MAX_DIFF_CHARS = 60_000
_MAX_TREE_LINES = 200

# Working-tree fallback bounds — a fallback that blows the context window is a
# different failure, not a fix.
_MAX_SCAN_FILES = 40
_MAX_SCAN_TOTAL_CHARS = 60_000
_MAX_SCAN_FILE_CHARS = 20_000

_SOURCE_SUFFIXES = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rb", ".rs", ".c", ".h",
    ".cpp", ".hpp", ".cs", ".php", ".kt", ".swift", ".scala", ".sh", ".bash",
    ".sql", ".yaml", ".yml", ".json", ".toml", ".ini", ".cfg",
}
_SPEC_SUFFIXES = {".md", ".markdown", ".txt", ".rst", ".csv"}
_SCAN_SUFFIXES = _SOURCE_SUFFIXES | _SPEC_SUFFIXES

_SKIP_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "env", "node_modules", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", "dist", "build",
    ".idea", ".vscode", "site-packages", ".next", "target", ".council_runs",
}


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


def _read_file(path: Path, limit: int = _MAX_SCAN_FILE_CHARS) -> tuple[str, bool]:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "", False
    return _truncate(raw, limit)


def _iter_candidate_files(base: Path) -> Iterable[Path]:
    """Walk the working tree, skipping vendor/build noise. Sorted for determinism."""

    stack = [base]
    while stack:
        current = stack.pop()
        try:
            entries = sorted(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir():
                if entry.name not in _SKIP_DIRS and not entry.name.startswith(".git"):
                    stack.append(entry)
            elif entry.is_file() and entry.suffix.lower() in _SCAN_SUFFIXES:
                yield entry


def _scan_working_tree(
    base: Path, warnings: List[str], already: Set[str]
) -> tuple[List[EvidenceItem], bool]:
    """Read source + spec files directly. Used when git yields no evidence.

    Spec files are read first: if the budget runs out, the requirements are the
    last thing a reviewer should lose.
    """

    files = [f for f in _iter_candidate_files(base) if str(f.resolve()) not in already]
    files.sort(key=lambda p: (p.suffix.lower() not in _SPEC_SUFFIXES, str(p).lower()))

    items: List[EvidenceItem] = []
    truncated = False
    budget = _MAX_SCAN_TOTAL_CHARS

    for path in files:
        if len(items) >= _MAX_SCAN_FILES or budget <= 0:
            truncated = True
            warnings.append(
                "working-tree scan hit its bound (%d files / %d chars); "
                "narrow --cwd or pass include= for a focused review."
                % (_MAX_SCAN_FILES, _MAX_SCAN_TOTAL_CHARS)
            )
            break
        content, was_cut = _read_file(path, min(_MAX_SCAN_FILE_CHARS, budget))
        if not content.strip():
            continue
        truncated = truncated or was_cut
        budget -= len(content)
        already.add(str(path.resolve()))
        try:
            rel = str(path.relative_to(base))
        except ValueError:
            rel = str(path)
        items.append(
            EvidenceItem(
                source_id=rel,
                source_type="file",
                title=rel,
                content=content,
                location=str(path),
                metadata={"suffix": path.suffix.lower()},
            )
        )
    return items, truncated


def _explicit_includes(
    base: Path, raw: str, warnings: List[str], already: Set[str]
) -> tuple[List[EvidenceItem], bool]:
    """Attach caller-named files/globs — typically the spec or brief."""

    items: List[EvidenceItem] = []
    truncated = False
    patterns = [p.strip() for p in raw.replace(",", "\n").splitlines() if p.strip()]

    for pattern in patterns:
        candidate = Path(pattern)
        matches = (
            [candidate]
            if candidate.is_absolute() and candidate.is_file()
            else sorted(base.glob(pattern))
        )
        if not matches:
            warnings.append(f"include pattern matched nothing: {pattern}")
            continue
        for path in matches:
            if not path.is_file() or str(path.resolve()) in already:
                continue
            content, was_cut = _read_file(path)
            if not content.strip():
                continue
            truncated = truncated or was_cut
            already.add(str(path.resolve()))
            try:
                rel = str(path.relative_to(base))
            except ValueError:
                rel = str(path)
            items.append(
                EvidenceItem(
                    source_id=rel,
                    source_type="file",
                    title=f"{rel} (explicitly included)",
                    content=content,
                    location=str(path),
                    metadata={"suffix": path.suffix.lower(), "included": "true"},
                )
            )
    return items, truncated


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
            if diff_scope:
                warnings.append(
                    f"diff scope '{diff_scope}' produced no diff; fell back to staged/HEAD."
                )
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
        else:
            warnings.append("Not a git repository (or empty index).")

        base = Path(cwd).resolve()
        seen: Set[str] = set()

        # Explicitly named files (the spec / brief) are attached whether or not git
        # worked. Without the requirements, a reviewer can only find style defects —
        # never "this violates what was asked for".
        include_arg = str((request.args or {}).get("include", "")).strip()
        if include_arg:
            included, was_cut = _explicit_includes(base, include_arg, warnings, seen)
            truncated = truncated or was_cut
            items.extend(included)

        # Fallback: git gave us nothing to review. Read the working tree directly
        # rather than convening advisors over an empty bundle.
        #
        # Keyed on git_diff alone, deliberately: an `include=` of one spec file must
        # not suppress the code scan, or the reviewer gets requirements and no code.
        # `seen` stops anything already included from being read twice.
        if not any(i.source_type == "git_diff" for i in items):
            scanned, was_cut = _scan_working_tree(base, warnings, seen)
            truncated = truncated or was_cut
            if scanned:
                warnings.append(
                    "No git evidence; fell back to reading %d working-tree file(s)."
                    % len(scanned)
                )
                items.extend(scanned)

        if not items:
            warnings.append(
                "No evidence could be gathered from %s — advisors would be reviewing "
                "nothing. Check --cwd, or pass --ground include=<path>." % cwd
            )

        rendered = "\n\n".join(i.content for i in items)
        return GroundingBundle(
            items=tuple(items),
            warnings=tuple(warnings),
            token_estimate=estimate_tokens(rendered),
            truncated=truncated,
        )
