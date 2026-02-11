"""Dart QA suppression strategy implementation."""

from typing import Any

# ── Language-specific constants ──────────────────────────────────
_LANGUAGE_NAME = "Dart"
_EXTENSIONS: tuple[str, ...] = (".dart",)
_FORBIDDEN_PATTERNS: tuple[str, ...] = (
    r"//\s*" + r"ignore:",
    r"//\s*" + r"ignore_for_file:",
)
_SKIP_DIRECTORIES: tuple[str, ...] = (
    ".dart_tool/",
    "build/",
    "vendor/",
)
_TOOL_NAMES: tuple[str, ...] = ("Dart Analyzer", "dart_code_metrics")
_TOOL_DOCS_URLS: tuple[str, ...] = (
    "https://dart.dev/tools/analysis",
    "https://dcm.dev/",
)


class DartQaSuppressionStrategy:
    """QA suppression strategy for Dart."""

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
        """Return acceptance tests for Dart QA suppression strategy."""
        from claude_code_hooks_daemon.core import AcceptanceTest, Decision, TestType

        return [
            AcceptanceTest(
                title="Dart QA suppression blocked",
                command=(
                    'Write file_path="/tmp/acceptance-test-qa-dart/example.dart"'
                    ' content="// ' + "ignore:" + ' unused_local_variable\\nvar x = 1;"'
                ),
                description="Should block Dart QA suppression comment",
                expected_decision=Decision.DENY,
                expected_message_patterns=["suppression", "BLOCKED", "Dart"],
                test_type=TestType.BLOCKING,
                safety_notes="Uses /tmp path - safe",
                setup_commands=["mkdir -p /tmp/acceptance-test-qa-dart"],
                cleanup_commands=["rm -rf /tmp/acceptance-test-qa-dart"],
            ),
        ]
