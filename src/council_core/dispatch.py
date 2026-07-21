"""Parallel advisor dispatch across pluggable backends.

Each persona runs on its configured backend and model. Grounded backends browse
the material themselves; non-grounded (provider) backends get the pack's
``GroundingBundle`` text injected into their prompt. Tasks are grouped by backend
so each backend runs its set concurrently. A single failed persona is captured as
a failed AdvisorResult and never sinks the run.
"""

from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List

from council_core.backends import BackendRegistry, BackendTask
from council_core.input import AdvisorResult, AgentOutcome, PersonaSpec
from council_core.metering import MeteringSink
from council_core.prompts import PromptSet


def dispatch_advisors(
    personas: List[PersonaSpec],
    brief: str,
    mode: str,
    cwd: str,
    grounding_text: str,
    prompt_set: PromptSet,
    meter: MeteringSink,
    registry: BackendRegistry,
) -> List[AdvisorResult]:
    if not personas:
        return []

    tasks_by_backend: Dict[str, List[BackendTask]] = defaultdict(list)
    for persona in personas:
        grounded = registry.get(persona.backend).grounded
        read_rule = (
            "- Read the actual material before forming any opinion."
            if grounded
            else "- Base your analysis strictly on the evidence above; cite it. Do not invent facts you cannot see."
        )
        prompt = prompt_set.build_advisor(
            persona=persona,
            brief=brief,
            mode=mode,
            grounded=grounded,
            grounding_text=grounding_text,
            read_rule=read_rule,
        )
        tasks_by_backend[persona.backend].append(
            BackendTask(task_id=persona.key, prompt=prompt, model=persona.model, params=persona.model_params)
        )

    outcomes_by_key: Dict[str, AgentOutcome] = {}

    def _run_group(item):
        backend_name, tasks = item
        backend = registry.get(backend_name)
        return list(zip(tasks, backend.run_batch(tasks, cwd=cwd)))

    with ThreadPoolExecutor(max_workers=max(1, len(tasks_by_backend))) as pool:
        for pairs in pool.map(_run_group, list(tasks_by_backend.items())):
            for task, outcome in pairs:
                outcomes_by_key[task.task_id] = outcome

    results: List[AdvisorResult] = []
    for persona in personas:
        outcome = outcomes_by_key.get(
            persona.key,
            AgentOutcome(status="error", text="", error_message="no outcome returned"),
        )
        meter.record("advisor", persona.key, persona.model, persona.family, outcome, backend=persona.backend)
        results.append(AdvisorResult(persona=persona, outcome=outcome))
    return results
