"""Pluggable grounding providers."""

from council_core.grounding.bundle import (
    EvidenceItem,
    GroundingBundle,
    GroundingRequest,
    estimate_tokens,
)
from council_core.grounding.documents import DocumentGrounding
from council_core.grounding.git_repo import GitRepoGrounding
from council_core.grounding.null import NullGrounding
from council_core.grounding.protocol import Grounding

_PROVIDERS = {
    "git_repo": GitRepoGrounding,
    "documents": DocumentGrounding,
    "null": NullGrounding,
}


def get_grounding(name: str) -> Grounding:
    """Instantiate a grounding provider by its manifest name."""

    key = (name or "null").strip().lower()
    provider = _PROVIDERS.get(key)
    if provider is None:
        raise ValueError(
            f"Unknown grounding provider '{name}'. Known: {', '.join(sorted(_PROVIDERS))}."
        )
    return provider()


__all__ = [
    "EvidenceItem",
    "GroundingBundle",
    "GroundingRequest",
    "Grounding",
    "GitRepoGrounding",
    "DocumentGrounding",
    "NullGrounding",
    "get_grounding",
    "estimate_tokens",
    "get_grounding",
]
