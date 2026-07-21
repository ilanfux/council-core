"""Typed grounding results.

A grounding provider returns a ``GroundingBundle`` — a set of evidence items with
provenance, plus warnings and truncation state — instead of a bare string. This
lets the Fact Analyst reason about evidence boundaries and lets ``NullGrounding``
be honest that no external evidence was available.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple


@dataclass(frozen=True)
class EvidenceItem:
    source_id: str
    source_type: str            # "git_diff" | "file" | "document" | ...
    content: str
    title: Optional[str] = None
    location: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class GroundingRequest:
    """What a grounding provider needs to gather evidence for a run."""

    brief: str
    cwd: str = "."
    args: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class GroundingBundle:
    items: Tuple[EvidenceItem, ...] = ()
    warnings: Tuple[str, ...] = ()
    token_estimate: int = 0
    truncated: bool = False

    @property
    def has_evidence(self) -> bool:
        return bool(self.items)

    def render(self) -> str:
        """Flatten to a text block for injection into non-grounded prompts."""

        if not self.items:
            note = "(no external evidence source was available)"
            if self.warnings:
                note += "\n" + "\n".join(f"- {w}" for w in self.warnings)
            return note
        blocks: List[str] = []
        for item in self.items:
            header = f"[{item.source_type}] {item.title or item.source_id}"
            if item.location:
                header += f" ({item.location})"
            blocks.append(f"{header}\n{item.content}")
        text = "\n\n".join(blocks)
        if self.truncated:
            text += "\n\n... [evidence truncated] ..."
        return text


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars/token). Good enough for budgeting/manifest."""

    return max(0, len(text) // 4)
