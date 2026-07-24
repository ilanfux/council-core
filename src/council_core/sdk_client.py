"""Thin, defensive wrapper around the Cursor SDK.

All interaction with the beta ``cursor-sdk`` package is isolated here so the rest
of the tool is insulated from surface changes.

Why async: the SDK's *synchronous* bridge reads its subprocess startup line with
``select.select()``, which on Windows only works on sockets (not pipes) and fails
with WinError 10038. The *async* bridge uses asyncio subprocess streams, which
work on Windows under the Proactor event loop. So we drive everything through the
async API and bridge each stage with ``asyncio.run()``.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple, Union

from council_core.backends.base import BackendError
from council_core.input import AgentOutcome

# A model selection is either a plain id string or a built ModelSelection dict.
ModelSpec = Union[str, Mapping[str, Any]]
# (task_id, prompt, model_spec) — task_id is opaque, used only to align results.
AgentTask = Tuple[str, str, ModelSpec]
# model id -> {param id -> set of allowed values}. Empty value-set means "any".
ModelParamCatalog = Dict[str, Dict[str, Set[str]]]


def build_model_selection(model_id: str, params: Optional[Mapping[str, str]] = None) -> Any:
    """Return a plain id string, or a ModelSelection dict when params are set.

    The SDK accepts ``model`` as ``str | ModelSelection | Mapping``. Params are
    family-specific (GPT/Codex use ``reasoning``, Claude uses ``effort``/``thinking``).
    """

    if not params:
        return model_id
    return {"id": model_id, "params": [{"id": str(k), "value": str(v)} for k, v in params.items()]}


class SdkUnavailableError(BackendError):
    """Raised when cursor-sdk is not importable or no API key is configured."""


def _require_api_key(explicit: Optional[str] = None) -> str:
    api_key = explicit or os.environ.get("CURSOR_API_KEY")
    if not api_key or not api_key.strip():
        raise SdkUnavailableError(
            "CURSOR_API_KEY is not set. Export your Cursor user or service-account "
            "key (see https://cursor.com/dashboard/integrations) before running the council."
        )
    return api_key.strip()


def _import_sdk():
    try:
        import cursor_sdk  # type: ignore
    except Exception as error:  # pragma: no cover - environment dependent
        raise SdkUnavailableError(
            "cursor-sdk is not installed. Install it with `pip install cursor-sdk` "
            f"(underlying error: {error})."
        ) from error
    return cursor_sdk


def _run_async(coro):
    """Run a coroutine on a fresh loop. Force the Proactor policy on Windows so
    asyncio subprocess pipes (used by the SDK bridge) work."""

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    return asyncio.run(coro)


def _fetch_raw_models(api_key: Optional[str] = None):
    """Launch the bridge once and return the raw models.list() payload."""

    key = _require_api_key(api_key)
    sdk = _import_sdk()

    async def _run():
        async with await sdk.AsyncClient.launch_bridge(
            workspace=os.getcwd(), allow_api_key_env_fallback=True
        ) as client:
            return await client.list_models(api_key=key)

    return _run_async(_run())


def list_models(api_key: Optional[str] = None) -> List[str]:
    """Return the model ids the calling account can use, best-effort."""

    return _extract_model_ids(_fetch_raw_models(api_key))


def discover_models(api_key: Optional[str] = None) -> Tuple[List[str], ModelParamCatalog]:
    """Return (available model ids, per-model supported param catalog) in one call.

    The param catalog lets the caller validate family-specific params (GPT/Codex
    ``reasoning``, Claude ``effort``/``thinking``, Gemini none) before sending them, so a
    config typo is dropped with a warning instead of failing a run at the bridge.
    """

    raw = _fetch_raw_models(api_key)
    return _extract_model_ids(raw), _extract_model_params(raw)


def run_agents_batch(
    tasks: Sequence[AgentTask], cwd: str, api_key: Optional[str] = None
) -> List[AgentOutcome]:
    """Run several one-shot local agents concurrently against ``cwd``.

    Uses a single async bridge and ``asyncio.gather``, preserving task order in the
    returned list. A startup failure (CursorAgentError: never executed) and a run
    failure (RunResult.status == 'error') are normalized distinctly. One failed
    task never sinks the batch.
    """

    if not tasks:
        return []
    key = _require_api_key(api_key)
    sdk = _import_sdk()
    cursor_agent_error = getattr(sdk, "CursorAgentError", Exception)

    async def _one(client, prompt: str, model: ModelSpec) -> AgentOutcome:
        try:
            result = await sdk.AsyncAgent.prompt(
                prompt,
                sdk.AgentOptions(api_key=key, model=model, local=sdk.LocalAgentOptions(cwd=cwd)),
                client=client,
            )
        except cursor_agent_error as error:  # startup failure: never executed
            return AgentOutcome(
                status="startup_error",
                text="",
                error_message=_safe_str(getattr(error, "message", error)),
            )
        except Exception as error:  # unexpected; treat as startup failure
            return AgentOutcome(status="startup_error", text="", error_message=_safe_str(error))
        return _normalize_result(result)

    async def _run() -> List[AgentOutcome]:
        async with await sdk.AsyncClient.launch_bridge(
            workspace=cwd, local=sdk.LocalAgentOptions(cwd=cwd), allow_api_key_env_fallback=True
        ) as client:
            return await asyncio.gather(
                *[_one(client, prompt, model) for (_id, prompt, model) in tasks]
            )

    return _run_async(_run())


def run_agent(
    prompt: str, model: ModelSpec, cwd: str, api_key: Optional[str] = None
) -> AgentOutcome:
    """Convenience wrapper for a single one-shot agent run."""

    return run_agents_batch([("single", prompt, model)], cwd=cwd, api_key=api_key)[0]


def _normalize_result(result) -> AgentOutcome:
    status = _safe_str(getattr(result, "status", "finished")) or "finished"
    text = _safe_str(getattr(result, "result", "") or getattr(result, "text", ""))
    run_id = _opt_str(getattr(result, "id", None))
    agent_id = _opt_str(getattr(result, "agent_id", None))
    duration_ms = _opt_int(getattr(result, "duration_ms", None))
    # When a ModelSelection (dict/object) is sent, the SDK echoes it back; record
    # just the id so metering stays a clean model name.
    raw_model = getattr(result, "model", None)
    if isinstance(raw_model, Mapping):
        raw_model = raw_model.get("id", raw_model)
    actual_model = _opt_str(getattr(raw_model, "id", raw_model))

    if status == "error":
        return AgentOutcome(
            status="error",
            text=text,
            run_id=run_id,
            agent_id=agent_id,
            error_message="agent run reported status=error",
            duration_ms=duration_ms,
            actual_model=actual_model,
        )
    return AgentOutcome(
        status="finished",
        text=text,
        run_id=run_id,
        agent_id=agent_id,
        duration_ms=duration_ms,
        actual_model=actual_model,
    )


def _unwrap_items(raw):
    """models.list() may return a list or a wrapper with .data/.models/.items."""

    items = raw
    for attr in ("data", "models", "items"):
        if hasattr(items, attr):
            items = getattr(items, attr)
            break
    return items


def _entry_id(entry) -> Optional[str]:
    if isinstance(entry, str):
        return entry
    model_id = getattr(entry, "id", None) or (entry.get("id") if isinstance(entry, dict) else None)
    return str(model_id) if model_id else None


def _extract_model_ids(raw) -> List[str]:
    """Pull model id strings out of whatever shape models.list() returns."""

    ids: List[str] = []
    try:
        for entry in _unwrap_items(raw):
            model_id = _entry_id(entry)
            if model_id:
                ids.append(model_id)
    except TypeError:
        pass
    return ids


def _extract_model_params(raw) -> ModelParamCatalog:
    """Map each model id to its supported parameters and allowed values.

    A model with no parameters (e.g. Gemini) maps to an empty dict. Values are
    captured so we can also reject out-of-range values, not just unknown params.
    """

    catalog: ModelParamCatalog = {}
    try:
        for entry in _unwrap_items(raw):
            model_id = _entry_id(entry)
            if not model_id or isinstance(entry, str):
                continue
            params = getattr(entry, "parameters", None)
            if params is None and isinstance(entry, dict):
                params = entry.get("parameters")
            param_map: Dict[str, Set[str]] = {}
            for p in params or []:
                pid = getattr(p, "id", None) or (p.get("id") if isinstance(p, dict) else None)
                if not pid:
                    continue
                raw_values = getattr(p, "values", None)
                if raw_values is None and isinstance(p, dict):
                    raw_values = p.get("values")
                values: Set[str] = set()
                for v in raw_values or []:
                    val = getattr(v, "value", None) or (v.get("value") if isinstance(v, dict) else None)
                    if val is not None:
                        values.add(str(val))
                param_map[str(pid)] = values
            catalog[model_id] = param_map
    except TypeError:
        pass
    return catalog


def _safe_str(value) -> str:
    try:
        return "" if value is None else str(value)
    except Exception:
        return ""


def _opt_str(value) -> Optional[str]:
    if value is None:
        return None
    return str(value)


def _opt_int(value) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
