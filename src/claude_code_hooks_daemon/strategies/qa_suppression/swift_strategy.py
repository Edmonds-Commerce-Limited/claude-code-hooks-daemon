"""Swift QA suppression strategy implementation."""

from typing import Any

# ── Language-specific constants ──────────────────────────────────
_LANGUAGE_NAME = "Swift"
_EXTENSIONS: tuple[str, ...] = (".swift",)
_FORBIDDEN_PATTERNS: tuple[str, ...] = (
    r"//\s*swiftlint:" + "disable",
    r"//\s*swift-format-" + "ignore",
)
_SKIP_DIRECTORIES: tuple[str, ...] = (
    ".build/",
    "Pods/",
    "vendor/",
)
_TOOL_NAMES: tuple[str, ...] = ("SwiftLint", "swift-format")
_TOOL_DOCS_URLS: tuple[str, ...] = (
    "https://realm.github.io/SwiftLint/",
    "https://github.com/apple/swift-format",
)


class SwiftQaSuppressionStrategy:
    """QA suppression strategy for Swift."""

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
        """Return acceptance tests for Swift QA suppression strategy."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="Swift QA suppression blocked",
                command=(
                    'Write file_path="/tmp/acceptance-test-qa-swift/Example.swift"'
                    ' content="// swiftlint:' + "disable" + ' force_cast\\nlet x = obj as! String"'
                ),
                description="Should block Swift QA suppression comment",
                expected_decision=Decision.DENY,
                expected_message_patterns=["suppression", "BLOCKED", "Swift"],
                test_type=TestType.BLOCKING,
                safety_notes="Uses /tmp path - safe",
                setup_commands=["mkdir -p /tmp/acceptance-test-qa-swift"],
                cleanup_commands=["rm -rf /tmp/acceptance-test-qa-swift"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
