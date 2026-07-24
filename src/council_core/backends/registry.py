"""Backend registry: build backend instances from configuration on demand.

Config maps a backend *name* (referenced by a persona's ``backend:``) to a
definition. The optional ``type`` aliases a name to an implementation, e.g. an
``openrouter`` backend of ``type: openai`` with its own base_url/key env.
Instances are cached so a single council reuses one client per backend.
"""

from __future__ import annotations

from typing import Dict

from council_core.backends.anthropic_backend import AnthropicBackend
from council_core.backends.base import Backend, BackendError
from council_core.backends.cursor import CursorBackend
from council_core.backends.google_backend import GoogleBackend
from council_core.backends.openai_backend import OpenAIBackend

_BUILDERS = {
    "cursor": lambda cfg: CursorBackend(api_key_env=cfg.get("api_key_env", "CURSOR_API_KEY")),
    "openai": lambda cfg: OpenAIBackend(
        api_key_env=cfg.get("api_key_env", "OPENAI_API_KEY"),
        base_url_env=cfg.get("base_url_env", "OPENAI_BASE_URL"),
        base_url=cfg.get("base_url"),
    ),
    "anthropic": lambda cfg: AnthropicBackend(api_key_env=cfg.get("api_key_env", "ANTHROPIC_API_KEY")),
    "google": lambda cfg: GoogleBackend(api_key_env=cfg.get("api_key_env", "GOOGLE_API_KEY")),
}


class BackendRegistry:
    def __init__(self, backends_config: Dict[str, dict]) -> None:
        self._config = backends_config or {}
        self._cache: Dict[str, Backend] = {}

    def get(self, name: str) -> Backend:
        key = (name or "google").strip().lower()
        if key in self._cache:
            return self._cache[key]
        cfg = self._config.get(key, {}) or {}
        backend_type = str(cfg.get("type") or key).strip().lower()
        builder = _BUILDERS.get(backend_type)
        if not builder:
            raise BackendError(
                f"Unknown backend '{name}' (resolved type '{backend_type}'). "
                f"Known types: {', '.join(sorted(_BUILDERS))}."
            )
        backend = builder(cfg)
        self._cache[key] = backend
        return backend

    def known_names(self) -> list:
        return sorted(set(self._config) | set(_BUILDERS))
