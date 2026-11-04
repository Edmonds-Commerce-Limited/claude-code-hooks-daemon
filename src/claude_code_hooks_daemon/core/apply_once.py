"""Thread-safe apply-once gate for lazily-built handler state.

The daemon dispatches requests on executor threads, so state built on first
use is shared across threads. The gate publishes "done" only AFTER the work
finished and makes concurrent first callers wait for it, so no caller ever
observes half-applied state (e.g. an unfiltered strategy registry) and two
threads never both mutate it.
"""

import threading
from collections.abc import Callable
from typing import Generic, Protocol, TypeVar


class ApplyOnce:
    """Run a callable exactly once (double-checked, re-entrant)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._done = False

    @property
    def done(self) -> bool:
        """True once the callable has completed successfully."""
        return self._done

    def run(self, fn: Callable[[], None]) -> None:
        """Run ``fn`` unless it already completed; a failure leaves the gate open."""
        if self._done:
            return
        with self._lock:
            if self._done:
                return
            fn()
            self._done = True


class _LanguageFilterable(Protocol):
    """A strategy registry that can be narrowed to a set of languages."""

    def filter_by_languages(self, language_names: list[str]) -> None: ...


_RegistryT = TypeVar("_RegistryT", bound=_LanguageFilterable)


class LazyLanguageFilterMixin(Generic[_RegistryT]):
    """Shared lazy ``registry.filter_by_languages`` for language-strategy handlers.

    The host sets ``_registry``, ``_languages``, ``_project_languages`` and a
    ``_language_gate`` (``ApplyOnce``). Options arrive via setattr AFTER
    ``__init__``, so filtering is deferred to the first matches()/handle().
    Priority: handler ``_languages`` > project ``_project_languages`` > all.
    """

    # Parameterised so each handler keeps its concrete registry type.
    _registry: _RegistryT
    _languages: list[str] | None
    _project_languages: list[str] | None
    _language_gate: ApplyOnce

    def _apply_language_filter(self) -> None:
        """Filter the registry once, atomically with respect to other threads."""
        self._language_gate.run(self._filter_registry_languages)

    def _filter_registry_languages(self) -> None:
        effective_languages = self._languages or self._project_languages
        if effective_languages:
            self._registry.filter_by_languages(effective_languages)
