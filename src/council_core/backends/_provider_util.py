"""Shared helpers for chat-style provider backends (OpenAI/Anthropic/Google).

Provider backends are stateless HTTP calls, so we fan them out with a thread
pool, preserve task order, and turn any per-task exception into a failed
AgentOutcome (never raising) so one persona can't sink the council.
"""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, List, Optional, Sequence

from council_core.backends.base import BackendTask
from council_core.input import AgentOutcome

_SYSTEM_PROMPT = (
    "You are a rigorous senior expert on an advisory council. Base every claim on "
    "the provided material, cite your evidence, and be specific and decisive."
)


def env_key(*names: str) -> Optional[str]:
    """Return the first non-empty environment variable among ``names``."""

    for name in names:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return None


def run_parallel(
    tasks: Sequence[BackendTask],
    call_one: Callable[[BackendTask], AgentOutcome],
    max_workers: int = 6,
) -> List[AgentOutcome]:
    """Run ``call_one`` for each task concurrently, preserving order."""

    if not tasks:
        return []

    def _guarded(task: BackendTask) -> AgentOutcome:
        started = time.perf_counter()
        try:
            return call_one(task)
        except Exception as error:  # any provider/transport error -> failed outcome
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            return AgentOutcome(
                status="error",
                text="",
                error_message=f"{type(error).__name__}: {error}",
                duration_ms=elapsed_ms,
                actual_model=task.model,
            )

    workers = max(1, min(max_workers, len(tasks)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(_guarded, tasks))


def finished(text: str, model: str, started: float) -> AgentOutcome:
    """Build a finished/empty outcome from response text and a start timestamp."""

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    body = (text or "").strip()
    if not body:
        return AgentOutcome(
            status="error",
            text="",
            error_message="provider returned empty response",
            duration_ms=elapsed_ms,
            actual_model=model,
        )
    return AgentOutcome(status="finished", text=body, duration_ms=elapsed_ms, actual_model=model)


def system_prompt() -> str:
    return _SYSTEM_PROMPT
