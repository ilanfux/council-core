"""Shared test fakes: offline backends so the whole pipeline is deterministic."""

from __future__ import annotations

import time
from typing import Callable, Dict, List, Optional, Sequence

import pytest

from council_core.backends.base import Backend, BackendTask
from council_core.input import AgentOutcome

# A verdict that satisfies every built-in output contract's required markers.
_CANNED_VERDICT = """## Council Verdict: test

### Conclusion
Proceed with the change.

### Must fix before merge (blocking)
- none

### Recommended action
Do the thing.

### Risks and irreversibility
Low; reversible.

### Next actions
Ship it.

### One concrete next action
Merge after CI.

### Verdict
SHIP — looks good.
"""


class FakeBackend(Backend):
    name = "fake"
    grounded = False

    def __init__(self, response_fn: Optional[Callable[[BackendTask], AgentOutcome]] = None,
                 fail_keys: Optional[set] = None) -> None:
        self._fn = response_fn
        self._fail_keys = fail_keys or set()

    def check_credentials(self) -> Optional[str]:
        return None

    def run_batch(self, tasks: Sequence[BackendTask], cwd: str) -> List[AgentOutcome]:
        out: List[AgentOutcome] = []
        for t in tasks:
            if self._fn is not None:
                out.append(self._fn(t))
                continue
            if t.task_id in self._fail_keys:
                out.append(AgentOutcome(status="error", text="", error_message="forced failure", actual_model=t.model))
            elif t.task_id == "chairman":
                out.append(AgentOutcome(status="finished", text=_CANNED_VERDICT, actual_model=t.model))
            elif t.task_id == "architect":
                out.append(AgentOutcome(status="finished", text=t.prompt, actual_model=t.model))
            else:
                out.append(AgentOutcome(status="finished", text=f"[{t.task_id}] analysis: finding X.", actual_model=t.model))
        return out


class FakeRegistry:
    """Returns one FakeBackend for every backend name."""

    def __init__(self, backend: Optional[FakeBackend] = None) -> None:
        self._backend = backend or FakeBackend()

    def get(self, name: str) -> FakeBackend:
        return self._backend


@pytest.fixture
def fake_registry() -> FakeRegistry:
    return FakeRegistry()


@pytest.fixture
def canned_verdict() -> str:
    return _CANNED_VERDICT
