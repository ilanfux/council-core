"""Backend abstraction: how a persona prompt actually gets executed.

Execution is pluggable:

- ``cursor``    - grounded local agent via the Cursor SDK (browses the repo).
- ``openai``    - OpenAI-compatible chat API (also covers gateways via base_url).
- ``anthropic`` - Anthropic Messages API.
- ``google``    - Google Gemini API.

Provider backends are plain chat calls: they cannot browse the repo, so the
dispatcher injects grounding context into their prompts.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Mapping, Optional, Sequence

from council_core.input import AgentOutcome


class BackendError(RuntimeError):
    """A backend cannot run (missing dependency, missing credentials, etc.)."""


@dataclass
class BackendTask:
    """One unit of work for a backend: a prompt on a model, with optional params."""

    task_id: str
    prompt: str
    model: str
    params: Mapping[str, str] = field(default_factory=dict)


class Backend(ABC):
    """A pluggable execution engine for persona prompts."""

    name: str = "base"
    grounded: bool = False

    @abstractmethod
    def check_credentials(self) -> Optional[str]:
        """None if usable, else a human-readable reason so the caller fails fast."""

    @abstractmethod
    def run_batch(self, tasks: Sequence[BackendTask], cwd: str) -> List[AgentOutcome]:
        """Run tasks (ideally concurrently) and return outcomes in task order.

        A single failed task must be returned as a failed AgentOutcome rather than
        raising, so one persona never sinks the whole council.
        """
