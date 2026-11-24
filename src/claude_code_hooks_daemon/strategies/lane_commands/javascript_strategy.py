"""JavaScript lane-command strategy - test runners, bundlers, linters, package scripts."""

from typing import Any

from claude_code_hooks_daemon.strategies.lane_commands.common import lane_acceptance_test

_LANGUAGE_NAME = "JavaScript"
_LANE_PATTERNS: tuple[str, ...] = (
    r"^(?:jest|vitest|playwright|mocha)\b",
    r"^(?:npm|yarn|pnpm|bun)\s+(?:test|run\s+test\S*)\b",
    # npm and pnpm document `t` as their alias for `test`.
    r"^(?:npm|pnpm)\s+t\b",
    r"^(?:npm|yarn|pnpm|bun)\s+(?:build|run\s+build\S*)\b",
    r"^(?:tsc|webpack)\b",
    r"^(?:eslint|prettier|stylelint)\b",
    r"^(?:npm|yarn|pnpm|bun)\s+(?:run\s+)?(?:llm:)?(?:lint|typecheck|type-check|qa)\S*",
    r"^npx\s+(?:jest|vitest|playwright|mocha|tsc|eslint|prettier)\b",
)
_ACCEPTANCE_COMMAND = "npm test"


class JavaScriptLaneCommandStrategy:
    """Lane commands for JavaScript and TypeScript projects."""

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def lane_patterns(self) -> tuple[str, ...]:
        return _LANE_PATTERNS

    def get_acceptance_tests(self) -> list[Any]:
        """A host seat's npm test run is refused."""
        return [lane_acceptance_test(_LANGUAGE_NAME, _ACCEPTANCE_COMMAND)]
