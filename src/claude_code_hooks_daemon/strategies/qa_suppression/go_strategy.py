"""Go QA suppression strategy implementation."""

from typing import Any

# ── Language-specific constants ──────────────────────────────────
_LANGUAGE_NAME = "Go"
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

        return [
            AcceptanceTest(
                title="Go QA suppression blocked",
                command=(
                    'Write file_path="/tmp/acceptance-test-qa-go/example.go"'
                    ' content="package main // no' + "lint" + '"'
                ),
                description="Should block Go QA suppression comment",
                expected_decision=Decision.DENY,
                expected_message_patterns=["suppression", "BLOCKED", "Go"],
                test_type=TestType.BLOCKING,
                safety_notes="Uses /tmp path - safe",
                setup_commands=["mkdir -p /tmp/acceptance-test-qa-go"],
                cleanup_commands=["rm -rf /tmp/acceptance-test-qa-go"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
