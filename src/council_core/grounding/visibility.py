"""Detect when document grounding is invisible to grounded backends.

Grounded backends (e.g. Cursor) do not receive the documents bundle injected into
their prompts — they are told to read material under ``--cwd``. Documents passed
via ``--ground documents=…`` with paths outside that cwd are therefore invisible
unless the user relocates them. This module surfaces that gap loudly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Sequence

from council_core.grounding.bundle import GroundingBundle


def path_under_cwd(location: str, cwd: str) -> bool:
    """True when ``location`` resolves to a path inside ``cwd`` (inclusive)."""

    try:
        loc = Path(location).resolve()
        base = Path(cwd or ".").resolve()
        loc.relative_to(base)
        return True
    except (OSError, ValueError):
        return False


def any_grounded_backend(council: Any, registry: Any) -> bool:
    """True if chairman or any convened advisor still uses a grounded backend."""

    personas = [council.chairman, *council.advisors]
    for persona in personas:
        try:
            if registry.get(persona.backend).grounded:
                return True
        except Exception:
            continue
    return False


def documents_outside_cwd(bundle: GroundingBundle, cwd: str) -> List[str]:
    """Return ``EvidenceItem.location`` values for document items not under cwd."""

    out: List[str] = []
    for item in bundle.items:
        if item.source_type != "document" or not item.location:
            continue
        if not path_under_cwd(item.location, cwd):
            out.append(item.location)
    return out


def invisible_document_locations(
    *,
    bundle: GroundingBundle,
    cwd: str,
    council: Any,
    registry: Any,
) -> List[str]:
    """Locations of documents that grounded agents cannot see via ``--cwd``.

    Cascade-aware: only fires when a convened persona still has a grounded
    backend *after* model resolution. Provider-only (or cascade-to-provider)
    runs inject the bundle and must not warn.
    """

    if getattr(council.grounding, "name", "") != "documents":
        return []
    if not any_grounded_backend(council, registry):
        return []
    return documents_outside_cwd(bundle, cwd)


def format_invisible_docs_banner(locations: Sequence[str]) -> str:
    """Fix-1-style single-line banner naming unreachable basenames."""

    names = [Path(p).name for p in locations]
    labeled = ", ".join(names)
    n = len(names)
    noun = "document" if n == 1 else "documents"
    return (
        f"WARNING: {n} {noun} not visible to grounded Cursor agents "
        f"(place under --cwd): {labeled}"
    )
