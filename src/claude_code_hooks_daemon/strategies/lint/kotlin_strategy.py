"""Kotlin lint strategy implementation."""

from typing import Any

from claude_code_hooks_daemon.strategies.lint.common import COMMON_SKIP_PATHS, lint_output_dir
from claude_code_hooks_daemon.utils.scratch_dir import scratch_path

# Language-specific constants
_LANGUAGE_NAME = "Kotlin"
_EXTENSIONS: tuple[str, ...] = (".kt",)
#: `-script` accepts a `.kts` script file, and this strategy is registered for
#: `.kt` only — so the previous command rejected every file it was ever given.
#: The trailing `2>&1` it also carried was never a redirect: `lint_on_edit`
#: splits with `shlex` and runs in list form with NO shell, so kotlinc received
#: it as a literal argument. Both defects were invisible on a box without
#: `kotlinc`, where the absent tool produced the ALLOW the command could not.
#: `-d` keeps the emitted classes out of the user's directory, as the Rust
#: strategy does with `--out-dir`; the destination comes from
#: :func:`lint_output_dir` rather than a literal, so it is unguessable and
#: private to this process.
_DEFAULT_LINT_COMMAND_TEMPLATE = "kotlinc -nowarn -d {out_dir} {{file}}"
_EXTENDED_LINT_COMMAND = "ktlint {file}"
#: Acceptance-test fixture directory, below the sanctioned scratch root.
_FIXTURE_DIR = "acceptance-test-lint-kotlin"


class KotlinLintStrategy:
    """Lint enforcement strategy for Kotlin files.

    Default: kotlinc (compilation check, class files discarded)
    Extended: ktlint (style and error detection)
    """

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def extensions(self) -> tuple[str, ...]:
        return _EXTENSIONS

    @property
    def default_lint_command(self) -> str:
        return _DEFAULT_LINT_COMMAND_TEMPLATE.format(out_dir=lint_output_dir())

    @property
    def extended_lint_command(self) -> str | None:
        return _EXTENDED_LINT_COMMAND

    @property
    def skip_paths(self) -> tuple[str, ...]:
        return COMMON_SKIP_PATHS

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Kotlin lint strategy."""
        from claude_code_hooks_daemon.constants import ToolName
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
            ToolPayload,
        )

        fixture_root = scratch_path(_FIXTURE_DIR)
        probe_valid = ToolPayload(
            tool_name=ToolName.WRITE,
            tool_input={
                "file_path": str(scratch_path(_FIXTURE_DIR, "valid.kt")),
                "content": 'fun main() { println("hello") }',
            },
        )
        probe_invalid = ToolPayload(
            tool_name=ToolName.WRITE,
            tool_input={
                "file_path": str(scratch_path(_FIXTURE_DIR, "invalid.kt")),
                "content": 'fun main( { println("hello") }',
            },
        )

        return [
            AcceptanceTest(
                title="Kotlin lint - valid code passes",
                command=probe_valid.as_instruction(),
                tool_payload=probe_valid,
                description="Valid Kotlin code should pass lint validation",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes=(
                    "Inside the gitignored scratch directory - safe. "
                    "Creates temporary Kotlin file."
                ),
                test_type=TestType.ADVISORY,
                setup_commands=[f"mkdir -p {fixture_root}"],
                cleanup_commands=[f"rm -rf {fixture_root}"],
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Kotlin lint - invalid code blocked",
                command=probe_invalid.as_instruction(),
                tool_payload=probe_invalid,
                description="Invalid Kotlin code (missing closing paren) should be blocked",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"Kotlin lint FAILED", r"invalid.kt"],
                safety_notes=(
                    "Inside the gitignored scratch directory - safe. "
                    "Creates temporary Kotlin file with syntax error."
                ),
                test_type=TestType.BLOCKING,
                required_tools=["kotlinc"],
                setup_commands=[f"mkdir -p {fixture_root}"],
                cleanup_commands=[f"rm -rf {fixture_root}"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
