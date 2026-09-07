"""Ruby lint strategy implementation."""

from typing import Any

from claude_code_hooks_daemon.strategies.lint.common import COMMON_SKIP_PATHS
from claude_code_hooks_daemon.utils.scratch_dir import scratch_path

# Language-specific constants
_LANGUAGE_NAME = "Ruby"
_EXTENSIONS: tuple[str, ...] = (".rb",)
_DEFAULT_LINT_COMMAND = "ruby -c {file}"
_EXTENDED_LINT_COMMAND = "rubocop {file}"
#: Acceptance-test fixture directory, below the sanctioned scratch root.
_FIXTURE_DIR = "acceptance-test-lint-ruby"


class RubyLintStrategy:
    """Lint enforcement strategy for Ruby files.

    Default: ruby -c (syntax check)
    Extended: rubocop (style and error detection)
    """

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def extensions(self) -> tuple[str, ...]:
        return _EXTENSIONS

    @property
    def default_lint_command(self) -> str:
        return _DEFAULT_LINT_COMMAND

    @property
    def extended_lint_command(self) -> str | None:
        return _EXTENDED_LINT_COMMAND

    @property
    def skip_paths(self) -> tuple[str, ...]:
        return COMMON_SKIP_PATHS

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Ruby lint strategy."""
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
                "file_path": str(scratch_path(_FIXTURE_DIR, "valid.rb")),
                "content": "puts 'hello'",
            },
        )
        probe_invalid = ToolPayload(
            tool_name=ToolName.WRITE,
            tool_input={
                "file_path": str(scratch_path(_FIXTURE_DIR, "invalid.rb")),
                "content": "def hello\n  puts 'missing end'",
            },
        )

        return [
            AcceptanceTest(
                title="Ruby lint - valid code passes",
                command=probe_valid.as_instruction(),
                tool_payload=probe_valid,
                description="Valid Ruby code should pass lint validation",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes=(
                    "Inside the gitignored scratch directory - safe. Creates temporary Ruby file."
                ),
                test_type=TestType.ADVISORY,
                setup_commands=[f"mkdir -p {fixture_root}"],
                cleanup_commands=[f"rm -rf {fixture_root}"],
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Ruby lint - invalid code blocked",
                command=probe_invalid.as_instruction(),
                tool_payload=probe_invalid,
                description="Invalid Ruby code (missing end) should be blocked",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"Ruby lint FAILED", r"invalid.rb"],
                safety_notes=(
                    "Inside the gitignored scratch directory - safe. "
                    "Creates temporary Ruby file with syntax error."
                ),
                test_type=TestType.BLOCKING,
                required_tools=["ruby"],
                setup_commands=[f"mkdir -p {fixture_root}"],
                cleanup_commands=[f"rm -rf {fixture_root}"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
