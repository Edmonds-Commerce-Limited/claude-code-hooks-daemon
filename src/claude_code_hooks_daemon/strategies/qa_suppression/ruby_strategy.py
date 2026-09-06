"""Ruby QA suppression strategy implementation."""

from typing import Any

from claude_code_hooks_daemon.utils.scratch_dir import scratch_path

# ── Language-specific constants ──────────────────────────────────
_LANGUAGE_NAME = "Ruby"
#: Acceptance-test fixture directory, below the sanctioned scratch root.
_FIXTURE_DIR = "acceptance-test-qa-ruby"
_EXTENSIONS: tuple[str, ...] = (".rb",)
_FORBIDDEN_PATTERNS: tuple[str, ...] = (
    r"#\s*rubocop:" + "disable",
    r"#\s*steep:" + "ignore",
)
_SKIP_DIRECTORIES: tuple[str, ...] = ("vendor/",)
_TOOL_NAMES: tuple[str, ...] = ("RuboCop", "Steep")
_TOOL_DOCS_URLS: tuple[str, ...] = (
    "https://rubocop.org/",
    "https://github.com/soutaro/steep",
)


class RubyQaSuppressionStrategy:
    """QA suppression strategy for Ruby."""

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def extensions(self) -> tuple[str, ...]:
        return _EXTENSIONS

    @property
    def forbidden_patterns(self) -> tuple[str, ...]:
        return _FORBIDDEN_PATTERNS

    @property
    def skip_directories(self) -> tuple[str, ...]:
        return _SKIP_DIRECTORIES

    @property
    def tool_names(self) -> tuple[str, ...]:
        return _TOOL_NAMES

    @property
    def tool_docs_urls(self) -> tuple[str, ...]:
        return _TOOL_DOCS_URLS

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Ruby QA suppression strategy."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        fixture_root = scratch_path(_FIXTURE_DIR)

        return [
            AcceptanceTest(
                title="Ruby QA suppression blocked",
                command=(
                    f'Write file_path="{scratch_path(_FIXTURE_DIR, "example.rb")}"'
                    ' content="# rubocop:' + "disable" + ' Style/FrozenStringLiteral\\nx = 1"'
                ),
                description="Should block Ruby QA suppression comment",
                expected_decision=Decision.DENY,
                expected_message_patterns=["suppression", "BLOCKED", "Ruby"],
                test_type=TestType.BLOCKING,
                safety_notes="Inside the gitignored scratch directory - safe",
                setup_commands=[f"mkdir -p {fixture_root}"],
                cleanup_commands=[f"rm -rf {fixture_root}"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
