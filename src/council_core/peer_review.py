"""Anonymized peer review.

Advisor responses are shuffled and relabeled A/B/C... so reviewers judge on
merit, not role. Each reviewer runs on a model from a DIFFERENT family than the
advisor it is paired with, so one family never both writes and grades the same
dominant finding.
"""

from __future__ import annotations

import random
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from string import ascii_uppercase
from typing import Dict, List, Optional, Tuple

from council_core.backends import BackendRegistry, BackendTask
from council_core.input import AdvisorResult, AgentOutcome, PeerReviewResult
from council_core.metering import MeteringSink
from council_core.prompts import PromptSet


def anonymize(advisors: List[AdvisorResult], rng: Optional[random.Random] = None) -> Dict[str, AdvisorResult]:
    """Return an ordered {letter: advisor} map over advisors with usable output."""

    usable = [a for a in advisors if a.outcome.ok]
    rng = rng or random.Random()
    shuffled = usable[:]
    rng.shuffle(shuffled)
    return {ascii_uppercase[i]: advisor for i, advisor in enumerate(shuffled)}


def pick_reviewer_model(
    advisor_family: str, pool: Dict[str, str], default_model: str, allow_same_family: bool = True
) -> Tuple[str, str, bool]:
    """Choose a (model, family, is_same_family) from a family != the advisor's.

    Returns a same-family flag so callers can surface a diversity-degradation
    warning rather than silently grading a response with its own family.
    """

    candidates = [(fam, model) for fam, model in pool.items() if fam != advisor_family and model]
    if candidates:
        family, model = candidates[0]
        return model, family, False
    if not allow_same_family:
        return "", advisor_family, True
    return default_model, advisor_family, True


def reviewer_backend_for(family: str, peer_review_backends: Dict[str, str], default_backend: str) -> str:
    return (peer_review_backends or {}).get(family, default_backend)


def run_peer_review(
    advisors: List[AdvisorResult],
    brief: str,
    prompt_set: PromptSet,
    cwd: str,
    peer_review_pool: Dict[str, str],
    default_model: str,
    meter: MeteringSink,
    registry: BackendRegistry,
    peer_review_backend: str,
    peer_review_backends: Optional[Dict[str, str]] = None,
    allow_same_family_fallback: bool = True,
    rng: Optional[random.Random] = None,
) -> Tuple[List[PeerReviewResult], List[str]]:
    anonymized = anonymize(advisors, rng=rng)
    warnings: List[str] = []
    if len(anonymized) < 2:
        return [], warnings

    anonymized_text = {letter: advisor.outcome.text.strip() for letter, advisor in anonymized.items()}
    prompt = prompt_set.build_peer(brief, anonymized_text)

    review_specs: List[Tuple[str, str, str, str]] = []  # (for_key, model, family, backend)
    for advisor in anonymized.values():
        model, family, same = pick_reviewer_model(
            advisor.persona.family, peer_review_pool, default_model, allow_same_family_fallback
        )
        if same:
            warnings.append(
                f"peer review of '{advisor.persona.key}' fell back to same family "
                f"'{advisor.persona.family}' (no cross-family reviewer configured)."
            )
        if not model:
            continue
        backend_name = reviewer_backend_for(family, peer_review_backends or {}, peer_review_backend)
        review_specs.append((advisor.persona.key, model, family, backend_name))

    tasks_by_backend: Dict[str, List[BackendTask]] = defaultdict(list)
    for (for_key, model, _family, backend_name) in review_specs:
        tasks_by_backend[backend_name].append(BackendTask(task_id=for_key, prompt=prompt, model=model))

    outcomes_by_key: Dict[str, AgentOutcome] = {}

    def _run_group(item):
        backend_name, tasks = item
        return list(zip(tasks, registry.get(backend_name).run_batch(tasks, cwd=cwd)))

    if tasks_by_backend:
        with ThreadPoolExecutor(max_workers=max(1, len(tasks_by_backend))) as pool:
            for pairs in pool.map(_run_group, list(tasks_by_backend.items())):
                for task, outcome in pairs:
                    outcomes_by_key[task.task_id] = outcome

    results: List[PeerReviewResult] = []
    for (for_key, model, family, backend_name) in review_specs:
        outcome = outcomes_by_key.get(
            for_key, AgentOutcome(status="error", text="", error_message="no outcome returned")
        )
        meter.record("peer", for_key, model, family, outcome, backend=backend_name)
        results.append(
            PeerReviewResult(
                reviewer_for_key=for_key,
                reviewer_model=model,
                reviewer_family=family,
                outcome=outcome,
            )
        )
    return results, warnings
