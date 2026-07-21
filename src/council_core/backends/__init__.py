"""Pluggable execution backends for the council."""

from council_core.backends.base import Backend, BackendError, BackendTask
from council_core.backends.registry import BackendRegistry

__all__ = ["Backend", "BackendError", "BackendTask", "BackendRegistry"]
