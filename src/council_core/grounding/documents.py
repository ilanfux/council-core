"""Document grounding (finance / career packs).

Documents are passed via grounding args (``documents`` = newline-delimited
``label::path`` or ``path`` entries, or ``documents_dir``). Text formats are
always supported; PDF/docx are extracted when optional deps are installed
(``pip install council-core[docs]``).
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Set, Tuple

from council_core.grounding.bundle import (
    EvidenceItem,
    GroundingBundle,
    GroundingRequest,
    estimate_tokens,
)

_MAX_FILE_CHARS = 40_000
_TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".csv", ".json", ".yaml", ".yml", ".log"}
_PDF_SUFFIXES = {".pdf"}
_DOCX_SUFFIXES = {".docx"}
_SUPPORTED_SUFFIXES = _TEXT_SUFFIXES | _PDF_SUFFIXES | _DOCX_SUFFIXES


def _truncate(raw: str) -> Tuple[str, bool]:
    if len(raw) <= _MAX_FILE_CHARS:
        return raw, False
    return raw[:_MAX_FILE_CHARS] + "\n... [truncated] ...", True


def _read_text(path: Path) -> Tuple[str, bool]:
    return _truncate(path.read_text(encoding="utf-8", errors="replace"))


def _read_pdf(path: Path) -> Tuple[str, bool, Optional[str]]:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception as error:
        return "", False, f"PDF support requires pypdf (`pip install council-core[docs]`): {error}"
    try:
        reader = PdfReader(str(path))
        parts: List[str] = []
        for page in reader.pages:
            parts.append(page.extract_text() or "")
        text, cut = _truncate("\n".join(parts).strip())
        if not text.strip():
            return "", False, f"PDF contained no extractable text: {path}"
        return text, cut, None
    except Exception as error:
        return "", False, f"failed to read PDF {path.name}: {error}"


def _read_docx(path: Path) -> Tuple[str, bool, Optional[str]]:
    try:
        import docx  # type: ignore  # python-docx
    except Exception as error:
        return "", False, f"DOCX support requires python-docx (`pip install council-core[docs]`): {error}"
    try:
        document = docx.Document(str(path))
        parts = [p.text for p in document.paragraphs if p.text]
        text, cut = _truncate("\n".join(parts).strip())
        if not text.strip():
            return "", False, f"DOCX contained no extractable text: {path}"
        return text, cut, None
    except Exception as error:
        return "", False, f"failed to read DOCX {path.name}: {error}"


def _read_document(path: Path) -> Tuple[str, bool, Optional[str]]:
    suffix = path.suffix.lower()
    if suffix in _TEXT_SUFFIXES:
        content, cut = _read_text(path)
        return content, cut, None
    if suffix in _PDF_SUFFIXES:
        return _read_pdf(path)
    if suffix in _DOCX_SUFFIXES:
        return _read_docx(path)
    return "", False, f"unsupported document type: {path}"


class DocumentGrounding:
    name = "documents"

    def gather(self, request: GroundingRequest) -> GroundingBundle:
        base = Path(request.cwd or ".")
        items: List[EvidenceItem] = []
        warnings: List[str] = []
        truncated = False
        allowed: Set[str] = set(_SUPPORTED_SUFFIXES)

        specs = str((request.args or {}).get("documents", "")).strip()
        entries = [line.strip() for line in specs.splitlines() if line.strip()] if specs else []

        docs_dir = str((request.args or {}).get("documents_dir", "")).strip()
        if docs_dir:
            dpath = (base / docs_dir) if not Path(docs_dir).is_absolute() else Path(docs_dir)
            if dpath.is_dir():
                for f in sorted(dpath.iterdir()):
                    if f.is_file() and f.suffix.lower() in allowed:
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
            if p.suffix.lower() not in allowed:
                warnings.append(
                    f"skipping unsupported document type (use text/markdown/pdf/docx): {raw_path}"
                )
                continue
            content, was_cut, error = _read_document(p)
            if error:
                warnings.append(error)
                continue
            truncated = truncated or was_cut
            items.append(
                EvidenceItem(
                    source_id=p.name,
                    source_type="document",
                    title=label.strip() or p.name,
                    content=content,
                    location=str(p),
                    metadata={"suffix": p.suffix.lower()},
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
