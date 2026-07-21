"""Chairman synthesis.

A single strong model receives the brief, the de-anonymized advisor analyses, and
the peer reviews, and produces the decisive verdict following the pack's output
contract skeleton. If the Chairman run fails, the caller falls back to a
locally-assembled digest so a council run always returns something useful.
"""

from __future__ import annotations

from typing import List

from council_core.backends import BackendRegistry, BackendTask
from council_core.input import AdvisorResult, AgentOutcome, PersonaSpec
from council_core.metering import MeteringSink
from council_core.output import OutputContract
from council_core.prompts import PromptSet


def run_chairman(
    chairman: PersonaSpec,
    advisors: List[AdvisorResult],
    peer_reviews: List[str],
    brief: str,
    prompt_set: PromptSet,
    output_contract: OutputContract,
    cwd: str,
    meter: MeteringSink,
    registry: BackendRegistry,
) -> AgentOutcome:
    prompt = prompt_set.build_chairman(brief, advisors, peer_reviews, output_contract.skeleton)
    backend = registry.get(chairman.backend)
    task = BackendTask(task_id="chairman", prompt=prompt, model=chairman.model, params=chairman.model_params)
    outcome = backend.run_batch([task], cwd=cwd)[0]
    meter.record("chairman", "chairman", chairman.model, chairman.family, outcome, backend=chairman.backend)
    return outcome
