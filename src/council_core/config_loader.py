"""Runtime engine config (backends + pools). NOT pack config — packs load via
``council_core.pack``.

Package defaults ship in ``council_core/defaults/backends.yaml``; users override
any subset by dropping ``~/.council/backends.yaml``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml

try:
    from importlib.resources import files as _resource_files
except Exception:  # pragma: no cover
    _resource_files = None  # type: ignore

from council_core.backends import BackendError, BackendRegistry
from council_core.env import credential_env_names, hydrate_persistent_env
from council_core.persona_architect import ModelAssignment

USER_CONFIG_DIR = Path(os.path.expanduser("~")) / ".council"


@dataclass
class RuntimeConfig:
    backends: Dict[str, dict]
    dynamic_pool: List[dict] = field(default_factory=list)
    chairman: Dict[str, str] = field(default_factory=dict)
    architect: Dict[str, str] = field(default_factory=dict)
    budget: Dict[str, float] = field(default_factory=dict)
    router: Dict[str, object] = field(default_factory=dict)

    def registry(self) -> BackendRegistry:
        return BackendRegistry(self.backends)

    @property
    def use_router_classifier(self) -> bool:
        return bool((self.router or {}).get("use_classifier", False))


def _read_default(filename: str) -> dict:
    if _resource_files is not None:
        text = _resource_files("council_core.defaults").joinpath(filename).read_text(encoding="utf-8")
    else:  # pragma: no cover
        text = (Path(__file__).parent / "defaults" / filename).read_text(encoding="utf-8")
    return yaml.safe_load(text) or {}


def _read_user_override(filename: str) -> dict:
    path = USER_CONFIG_DIR / filename
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _deep_merge(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_runtime_config() -> RuntimeConfig:
    raw = _deep_merge(_read_default("backends.yaml"), _read_user_override("backends.yaml"))
    config = RuntimeConfig(
        backends={str(k).lower(): dict(v or {}) for k, v in (raw.get("backends") or {}).items()},
        dynamic_pool=list(raw.get("dynamic_pool") or []),
        chairman=dict(raw.get("chairman") or {}),
        architect=dict(raw.get("architect") or {}),
        budget=dict(raw.get("budget") or {}),
        router=dict(raw.get("router") or {}),
    )
    hydrate_persistent_env(credential_env_names(config.backends))
    return config


def ready_backends(config: RuntimeConfig, registry: BackendRegistry) -> Dict[str, Optional[str]]:
    """Map backend name -> None if ready, else reason."""

    status: Dict[str, Optional[str]] = {}
    for name in config.backends:
        try:
            status[name] = registry.get(name).check_credentials()
        except BackendError as error:
            status[name] = str(error)
    return status


def available_assignments(config: RuntimeConfig, registry: BackendRegistry) -> List[ModelAssignment]:
    """dynamic_pool entries whose backend has ready credentials."""

    out: List[ModelAssignment] = []
    for entry in config.dynamic_pool:
        backend = str(entry.get("backend", "")).strip().lower()
        model = str(entry.get("model", "")).strip()
        family = str(entry.get("family", backend)).strip().lower()
        if not backend or not model:
            continue
        try:
            if registry.get(backend).check_credentials() is None:
                out.append(ModelAssignment(backend=backend, model=model, family=family))
        except BackendError:
            continue
    return out
