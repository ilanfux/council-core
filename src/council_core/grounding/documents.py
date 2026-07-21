"""Document grounding (finance / career packs).

v1 scope: treat user-supplied document text as evidence. Documents are passed via
the grounding args (``documents`` = newline-delimited ``label::path`` or ``path``
entries, or ``documents_dir`` = a folder of text/markdown files). Binary parsing
(PDF/docx) is deliberately out of scope for v1 — the pack asks the user to paste
or export text — but each file becomes a distinct, provenance-tagged evidence
item so the Fact Analyst can cite sources.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from council_core.grounding.bundle import (
    EvidenceItem,
    GroundingBundle,
    GroundingRequest,
    estimate_tokens,
)

_MAX_FILE_CHARS = 40_000
_TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".csv", ".json", ".yaml", ".yml", ".log"}


def _read_text(path: Path) -> tuple[str, bool]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    if len(raw) <= _MAX_FILE_CHARS:
        return raw, False
    return raw[:_MAX_FILE_CHARS] + "\n... [truncated] ...", True


class DocumentGrounding:
    name = "documents"

    def gather(self, request: GroundingRequest) -> GroundingBundle:
        base = Path(request.cwd or ".")
        items: List[EvidenceItem] = []
        warnings: List[str] = []
        truncated = False

        specs = str((request.args or {}).get("documents", "")).strip()
        entries = [line.strip() for line in specs.splitlines() if line.strip()] if specs else []

        docs_dir = str((request.args or {}).get("documents_dir", "")).strip()
        if docs_dir:
            dpath = (base / docs_dir) if not Path(docs_dir).is_absolute() else Path(docs_dir)
            if dpath.is_dir():
                for f in sorted(dpath.iterdir()):
                    if f.is_file() and f.suffix.lower() in _TEXT_SUFFIXES:
                        entries.append(str(f))
            else:
                warnings.append(f"documents_dir not found: {docs_dir}")

        for entry in entries:
            label, _, raw_path = entry.partition("::")
            if not raw_path:
                label, raw_path = "", entry
            p = Path(raw_path)
            if not p.is_absolute():
                p = base / raw_path
            if not p.is_file():
                warnings.append(f"document not found: {raw_path}")
                continue
            if p.suffix.lower() not in _TEXT_SUFFIXES:
                warnings.append(
                    f"skipping non-text document (v1 needs text/markdown; export it first): {raw_path}"
                )
                continue
            content, was_cut = _read_text(p)
            truncated = truncated or was_cut
            items.append(
                EvidenceItem(
                    source_id=p.name,
                    source_type="document",
                    title=label.strip() or p.name,
                    content=content,
                    location=str(p),
                )
            )

        if not items and not warnings:
            warnings.append(
                "No documents were supplied. Provide grounding args 'documents' "
                "(label::path per line) or 'documents_dir'."
            )

        rendered = "\n\n".join(i.content for i in items)
        return GroundingBundle(
            items=tuple(items),
            warnings=tuple(warnings),
            token_estimate=estimate_tokens(rendered),
            truncated=truncated,
        )
