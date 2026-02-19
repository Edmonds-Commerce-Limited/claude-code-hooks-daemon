"""Go error-hiding strategy - patterns that suppress errors in Go code."""

from typing import Any

from claude_code_hooks_daemon.strategies.error_hiding.protocol import ErrorHidingPattern

_LANGUAGE_NAME = "Go"
_EXTENSIONS: tuple[str, ...] = (".go",)

_PATTERNS: tuple[ErrorHidingPattern, ...] = (
    ErrorHidingPattern(
        name="empty error check",
        regex=r"if\s+err\s*!=\s*nil\s*\{\s*\}",
        example="if err != nil {}",
        suggestion="Return or handle the error; never ignore it",
    ),
    ErrorHidingPattern(
        name="blank identifier discards error",
        regex=r"\w+\s*,\s*_\s*:?=\s*\w|\b_\s*,\s*\w+\s*:?=\s*\w",
        example="result, _ := riskyCall()",
        suggestion="Capture and check the error return value",
    ),
)


class GoErrorHidingStrategy:
    """Error-hiding strategy for Go source files (.go)."""

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def extensions(self) -> tuple[str, ...]:
        return _EXTENSIONS

    @property
    def patterns(self) -> tuple[ErrorHidingPattern, ...]:
        return _PATTERNS

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Go error-hiding strategy."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="Go: empty error check ignores error value",
                command=(
                    "Write(\n"
                    "  file_path='/tmp/acceptance-test-error-hiding/go/bad.go',\n"
                    "  content='package main\\nfunc main() { if err != nil {} }'\n"
                    ")"
                ),
                description=("Blocks Go file with empty error check written via Write tool"),
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"Error-hiding pattern detected",
                    r"empty error check",
                ],
                safety_notes="Uses Write tool to a /tmp path",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Go: proper error handling is allowed",
                command=(
                    "Write(\n"
                    "  file_path='/tmp/acceptance-test-error-hiding/go/good.go',\n"
                    '  content=\'package main\\nimport "fmt"\\n'
                    "func main() {\\n  if err != nil { fmt.Println(err) }\\n}'\n"
                    ")"
                ),
                description=("Allows Go file with proper error handling via Write tool"),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Uses Write tool to a /tmp path",
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]
