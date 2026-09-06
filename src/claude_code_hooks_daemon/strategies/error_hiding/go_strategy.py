"""Go error-hiding strategy - patterns that suppress errors in Go code."""

from typing import Any

from claude_code_hooks_daemon.strategies.error_hiding.protocol import ErrorHidingPattern
from claude_code_hooks_daemon.utils.scratch_dir import scratch_path

_LANGUAGE_NAME = "Go"
#: Acceptance-test fixture directory, below the sanctioned scratch root.
_FIXTURE_DIR = "acceptance-test-error-hiding-go"
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
        # Only a blank in the LAST tuple position hides an error: Go returns
        # the error last, so `result, _ :=` throws it away, while the
        # idiomatic `_, err :=` captures it for the caller to check.
        regex=r"\w+\s*,\s*_\s*:?=\s*\w",
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

        fixture_root = scratch_path(_FIXTURE_DIR)

        return [
            AcceptanceTest(
                title="Go: empty error check ignores error value",
                command=(
                    "Write(\n"
                    f"  file_path='{scratch_path(_FIXTURE_DIR, 'bad.go')}',\n"
                    "  content='package main\\nfunc main() { if err != nil {} }'\n"
                    ")"
                ),
                description=("Blocks Go file with empty error check written via Write tool"),
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"BLOCKED \[R-ERROR-HIDING\]",
                    r"empty error check",
                ],
                safety_notes="Inside the gitignored scratch directory - safe",
                test_type=TestType.BLOCKING,
                setup_commands=[f"mkdir -p {fixture_root}"],
                cleanup_commands=[f"rm -rf {fixture_root}"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Go: proper error handling is allowed",
                command=(
                    "Write(\n"
                    f"  file_path='{scratch_path(_FIXTURE_DIR, 'good.go')}',\n"
                    '  content=\'package main\\nimport ("fmt"; "os")\\n'
                    'func main() {\\n  if _, err := os.Open(\\"f\\"); err != nil '
                    "{ fmt.Println(err) }\\n}'\n"
                    ")"
                ),
                description=("Allows Go file with proper error handling via Write tool"),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Inside the gitignored scratch directory - safe",
                test_type=TestType.ADVISORY,
                setup_commands=[f"mkdir -p {fixture_root}"],
                cleanup_commands=[f"rm -rf {fixture_root}"],
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]
