"""Python lane-command strategy - test runners, packaging builds, linters, type checkers."""

from typing import Any

from claude_code_hooks_daemon.strategies.lane_commands.common import lane_acceptance_test

_LANGUAGE_NAME = "Python"
_LANE_PATTERNS: tuple[str, ...] = (
    r"^(?:pytest|py\.test|tox|nox)\b",
    r"^uv\s+build\b",
    r"^(?:ruff|mypy|pyright|pylint|flake8|black|isort|bandit)\b",
    # `python -m unittest` peels to `unittest`.
    r"^unittest\b",
)
_ACCEPTANCE_COMMAND = "pytest tests/unit"


class PythonLaneCommandStrategy:
    """Lane commands for Python projects."""

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def lane_patterns(self) -> tuple[str, ...]:
        return _LANE_PATTERNS

    def get_acceptance_tests(self) -> list[Any]:
        """A host seat's pytest run is refused."""
        return [lane_acceptance_test(_LANGUAGE_NAME, _ACCEPTANCE_COMMAND)]
