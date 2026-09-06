"""Go QA suppression strategy implementation."""

from typing import Any

from claude_code_hooks_daemon.utils.scratch_dir import scratch_path

# ── Language-specific constants ──────────────────────────────────
_LANGUAGE_NAME = "Go"
#: Acceptance-test fixture directory, below the sanctioned scratch root.
_FIXTURE_DIR = "acceptance-test-qa-go"
_EXTENSIONS: tuple[str, ...] = (".go",)
_FORBIDDEN_PATTERNS: tuple[str, ...] = (
    r"//\s*no" + "lint",
    r"//\s*lint:" + "ignore",
)
_SKIP_DIRECTORIES: tuple[str, ...] = (
    "vendor/",
    "testdata/",
)
_TOOL_NAMES: tuple[str, ...] = ("golangci-lint", "golint")
_TOOL_DOCS_URLS: tuple[str, ...] = (
    "https://golangci-lint.run/",
    "https://go.dev/doc/effective_go",
    "https://github.com/golang/go/wiki/CodeReviewComments",
)


class GoQaSuppressionStrategy:
    """QA suppression strategy for Go."""

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
        """Return acceptance tests for Go QA suppression strategy."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        fixture_root = scratch_path(_FIXTURE_DIR)

        return [
            AcceptanceTest(
                title="Go QA suppression blocked",
                command=(
                    f'Write file_path="{scratch_path(_FIXTURE_DIR, "example.go")}"'
                    ' content="package main // no' + "lint" + '"'
                ),
                description="Should block Go QA suppression comment",
                expected_decision=Decision.DENY,
                expected_message_patterns=["suppression", "BLOCKED", "Go"],
                test_type=TestType.BLOCKING,
                safety_notes="Inside the gitignored scratch directory - safe",
                setup_commands=[f"mkdir -p {fixture_root}"],
                cleanup_commands=[f"rm -rf {fixture_root}"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
