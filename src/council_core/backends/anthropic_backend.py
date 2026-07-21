"""Anthropic (Claude) backend via the Messages API.

A plain chat call, so the persona prompt must already carry the grounding
context (injected by the dispatcher for non-grounded backends).
"""

from __future__ import annotations

import time
from typing import List, Optional, Sequence

from council_core.backends._provider_util import env_key, finished, run_parallel, system_prompt
from council_core.backends.base import Backend, BackendTask
from council_core.input import AgentOutcome

_DEFAULT_MAX_TOKENS = 8192


class AnthropicBackend(Backend):
    name = "anthropic"
    grounded = False

    def __init__(self, api_key_env: str = "ANTHROPIC_API_KEY", max_tokens: int = _DEFAULT_MAX_TOKENS) -> None:
        self.api_key_env = api_key_env
        self.max_tokens = max_tokens

    def _client(self):
        from anthropic import Anthropic  # lazy: optional dependency

        return Anthropic(api_key=env_key(self.api_key_env))

    def check_credentials(self) -> Optional[str]:
        try:
            import anthropic  # type: ignore  # noqa: F401
        except Exception as error:
            return f"anthropic package not installed (`pip install 'council-core[anthropic]'`): {error}"
        if not env_key(self.api_key_env):
            return f"{self.api_key_env} is not set (export your Anthropic API key)."
        return None

    def run_batch(self, tasks: Sequence[BackendTask], cwd: str) -> List[AgentOutcome]:
        client = self._client()

        def _one(task: BackendTask) -> AgentOutcome:
            started = time.perf_counter()
            resp = client.messages.create(
                model=task.model,
                max_tokens=self.max_tokens,
                system=system_prompt(),
                messages=[{"role": "user", "content": task.prompt}],
            )
            parts = [getattr(block, "text", "") for block in getattr(resp, "content", []) or []]
            return finished("".join(parts), getattr(resp, "model", task.model), started)

        return run_parallel(tasks, _one)
