"""Universal lane-command strategy - language-neutral build drivers, QA scripts, hooks."""

from typing import Any

from claude_code_hooks_daemon.strategies.lane_commands.common import lane_acceptance_test

_LANGUAGE_NAME = "Universal"
_LANE_PATTERNS: tuple[str, ...] = (
    r"^(?:llm_qa\.py|run_all\.sh)\b",
    # `make` alone, or a test/build/lint target. `make deploy` is untouched.
    r"^make(?:\s+-\S+)*\s*$",
    r"^make(?:\s+-\S+)*\s+(?:test|tests|check|lint|build|qa|all|ci)\b",
    r"^(?:cmake|ninja|bazel)\b",
    r"^(?:hadolint|markdownlint|yamllint)\b",
    r"^pre-commit\s+run\b",
    # A script named for tests, QA or lint: `run_tests.sh`, `llm_qa.py`, `test_x.py`.
    # A deploy, smoke, health, publish or connection check is triage even when
    # its name carries `test` or `qa` (`deploy-qa.sh`, `smoke_test.sh`).
    r"^(?![\w.-]*(?:deploy|smoke|health|publish|connection))"
    r"(?:[\w.-]*[_.-])?(?:tests?|qa|lint|typecheck|type_check)(?:[_.-][\w.-]*)?\.(?:sh|bash|py)\b",
)
_ACCEPTANCE_COMMAND = "make test"


class UniversalLaneCommandStrategy:
    """Lane commands that belong to no single language."""

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def lane_patterns(self) -> tuple[str, ...]:
        return _LANE_PATTERNS

    def get_acceptance_tests(self) -> list[Any]:
        """A host seat's make test run is refused."""
        return [lane_acceptance_test(_LANGUAGE_NAME, _ACCEPTANCE_COMMAND)]
