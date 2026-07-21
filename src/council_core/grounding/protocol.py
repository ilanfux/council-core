"""Grounding provider protocol.

Synchronous by design: the whole engine is ThreadPoolExecutor-based with no
asyncio, so an async ``gather`` would force an async boundary nothing else needs.
Revisit only if the orchestration model moves to asyncio wholesale.
"""

from __future__ import annotations

from typing import Protocol

from council_core.grounding.bundle import GroundingBundle, GroundingRequest


class Grounding(Protocol):
    #: Stable id referenced by a pack manifest (``grounding.provider``).
    name: str

    def gather(self, request: GroundingRequest) -> GroundingBundle:
        ...
