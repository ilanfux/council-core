"""Google Gemini backend via the google-genai SDK.

A plain content-generation call, so the persona prompt must already carry the
grounding context (injected by the dispatcher for non-grounded backends).
"""

from __future__ import annotations

import time
from typing import List, Optional, Sequence

from council_core.backends._provider_util import env_key, finished, run_parallel, system_prompt
from council_core.backends.base import Backend, BackendTask
from council_core.input import AgentOutcome


class GoogleBackend(Backend):
    name = "google"
    grounded = False

    def __init__(self, api_key_env: str = "GOOGLE_API_KEY") -> None:
        self.api_key_env = api_key_env

    def _client(self):
        from google import genai  # lazy: optional dependency

        return genai.Client(api_key=env_key(self.api_key_env, "GEMINI_API_KEY"))

    def check_credentials(self) -> Optional[str]:
        try:
            from google import genai  # type: ignore  # noqa: F401
        except Exception as error:
            return f"google-genai not installed (`pip install 'council-core[google]'`): {error}"
        if not env_key(self.api_key_env, "GEMINI_API_KEY"):
            return f"{self.api_key_env} (or GEMINI_API_KEY) is not set (export your Google AI key)."
        return None

    def run_batch(self, tasks: Sequence[BackendTask], cwd: str) -> List[AgentOutcome]:
        client = self._client()

        def _one(task: BackendTask) -> AgentOutcome:
            started = time.perf_counter()
            prompt = f"{system_prompt()}\n\n{task.prompt}"
            resp = client.models.generate_content(model=task.model, contents=prompt)
            return finished(getattr(resp, "text", "") or "", task.model, started)

        return run_parallel(tasks, _one)
