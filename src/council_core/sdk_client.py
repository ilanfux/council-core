"""Cursor SDK glue (optional backend).

The Cursor backend runs grounded local agents that browse the repo. It requires
the ``cursor-sdk`` package and a ``CURSOR_API_KEY``. council_core ships with the
provider backends (OpenAI-compatible / Anthropic / Google) as the primary path;
this module keeps the Cursor option available without making cursor-sdk a hard
dependency. If cursor-sdk is absent, calls raise BackendError with guidance.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from council_core.backends.base import BackendError
from council_core.input import AgentOutcome


class SdkUnavailableError(BackendError):
    """The Cursor SDK (or model discovery) is unavailable."""


# model id -> {param id -> allowed values}
ModelParamCatalog = Dict[str, Dict[str, set]]


def _import_sdk():
    try:
        import cursor_sdk  # type: ignore
    except Exception as error:  # pragma: no cover - environment dependent
        raise SdkUnavailableError(
            "cursor-sdk is not installed. Install it (`pip install cursor-sdk`) and set "
            "CURSOR_API_KEY, or use a provider backend (openai/anthropic/google)."
        ) from error
    return cursor_sdk


def build_model_selection(model: str, params: Optional[Dict[str, str]] = None):
    """Return an SDK model-selection object; kept minimal and lazy."""

    _import_sdk()
    return {"model": model, "params": dict(params or {})}


def run_agents_batch(
    sdk_tasks: Sequence[Tuple[str, str, object]],
    cwd: str,
    api_key: Optional[str],
) -> List[AgentOutcome]:  # pragma: no cover - requires cursor-sdk + key
    _import_sdk()
    raise SdkUnavailableError(
        "The Cursor grounded backend is not wired in this council_core build. "
        "Use a provider backend (openai/anthropic/google) or extend sdk_client.py."
    )


def discover_models(api_key: Optional[str]) -> Tuple[List[str], ModelParamCatalog]:
    """Best-effort Cursor model discovery. Absent SDK -> raise so callers fail fast."""

    _import_sdk()  # pragma: no cover
    raise SdkUnavailableError("Cursor model discovery unavailable in this build.")
