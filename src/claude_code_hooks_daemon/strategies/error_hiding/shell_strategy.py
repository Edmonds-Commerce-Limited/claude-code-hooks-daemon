"""Shell error-hiding strategy - patterns that suppress errors in shell scripts."""

from typing import Any

from claude_code_hooks_daemon.strategies.error_hiding.protocol import ErrorHidingPattern
from claude_code_hooks_daemon.utils.scratch_dir import scratch_path

_LANGUAGE_NAME = "Shell"
#: Acceptance-test fixture directory, below the sanctioned scratch root.
_FIXTURE_DIR = "acceptance-test-error-hiding-shell"
_EXTENSIONS: tuple[str, ...] = (".sh", ".bash")

_PATTERNS: tuple[ErrorHidingPattern, ...] = (
    ErrorHidingPattern(
        name="|| true",
        regex=r"\|\|\s*true\b",
        example="some_command || true",
        suggestion="Handle failure explicitly with if/else or exit 1",
    ),
    ErrorHidingPattern(
        name="|| :",
        regex=r"\|\|\s*:\s*(?:$|#|\n)",
        example="some_command || :",
        suggestion="Handle failure explicitly with if/else or exit 1",
    ),
    ErrorHidingPattern(
        name="set +e",
        regex=r"\bset\s+\+e\b",
        example="set +e",
        suggestion="Remove set +e; handle individual command failures with if/else",
    ),
    ErrorHidingPattern(
        name="&>/dev/null",
        regex=r"&>\s*/dev/null",
        example="some_command &>/dev/null",
        suggestion="Redirect only what you intend; log errors to a file or stderr",
    ),
    ErrorHidingPattern(
        name=">/dev/null 2>&1",
        regex=r">\s*/dev/null\s+2>&1",
        example="some_command >/dev/null 2>&1",
        suggestion="Redirect only what you intend; log errors to a file or stderr",
    ),
    ErrorHidingPattern(
        name="trap '' ERR",
        regex=r"trap\s+['\"]?\s*['\"]?\s+ERR\b",
        example="trap '' ERR",
        suggestion="Remove the trap or handle errors explicitly",
    ),
)


class ShellErrorHidingStrategy:
    """Error-hiding strategy for shell scripts (.sh, .bash)."""

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
        """Return acceptance tests for Shell error-hiding strategy."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        fixture_root = scratch_path(_FIXTURE_DIR)

        return [
            AcceptanceTest(
                title="Shell: || true hides command failure",
                command=(
                    "Write(\n"
                    f"  file_path='{scratch_path(_FIXTURE_DIR, 'bad.sh')}',\n"
                    "  content='#!/bin/bash\\nsome_command || true\\n'\n"
                    ")"
                ),
                description=(
                    "Blocks shell script with '|| true' error-hiding pattern "
                    "written via Write tool"
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"BLOCKED \[R-ERROR-HIDING\]",
                    r"\|\| true",
                ],
                safety_notes="Inside the gitignored scratch directory - safe",
                test_type=TestType.BLOCKING,
                setup_commands=[f"mkdir -p {fixture_root}"],
                cleanup_commands=[f"rm -rf {fixture_root}"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Shell: clean script with explicit error handling is allowed",
                command=(
                    "Write(\n"
                    f"  file_path='{scratch_path(_FIXTURE_DIR, 'good.sh')}',\n"
                    "  content='#!/bin/bash\\nset -euo pipefail\\n"
                    "cmd || { echo failed >&2; exit 1; }\\n'\n"
                    ")"
                ),
                description=("Allows shell script with proper error handling via Write tool"),
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
