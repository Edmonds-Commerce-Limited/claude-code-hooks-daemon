"""LaneCommandStrategy Protocol - one language's test, build, lint and QA commands."""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class LaneCommandStrategy(Protocol):
    """Strategy interface for the commands a worker lane runs and a host seat does not.

    The list is deliberately SHORT: the common test, build, lint and QA
    command names of one language, not every spelling of them. Patterns are
    matched against the PEELED ``program args`` produced by
    :mod:`utils.long_running_command` (``python -m pytest``, ``uv run pytest``,
    ``timeout 9 pytest`` and ``sh -c 'pytest'`` all arrive as ``pytest ...``),
    so a pattern names the program, never its wrappers.

    To add a language: implement this Protocol and register it in
    ``LaneCommandStrategyRegistry.create_default``.
    """

    @property
    def language_name(self) -> str:
        """Human-readable language name (e.g. 'Python', 'Universal')."""
        ...

    @property
    def lane_patterns(self) -> tuple[str, ...]:
        """Regexes for this language's lane commands, anchored at the program word."""
        ...

    def get_acceptance_tests(self) -> list[Any]:
        """Acceptance tests for this strategy; at least one, a lane refusal."""
        ...
