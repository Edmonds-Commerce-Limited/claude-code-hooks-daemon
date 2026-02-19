"""Java QA suppression strategy implementation."""

from typing import Any

# ── Language-specific constants ──────────────────────────────────
_LANGUAGE_NAME = "Java"
_EXTENSIONS: tuple[str, ...] = (".java",)
_FORBIDDEN_PATTERNS: tuple[str, ...] = (
    r"@Suppress" + "Warnings",
    r"//\s*CHECKSTYLE" + ":OFF",
    r"//\s*NO" + "SONAR",
    r"//\s*spotbugs" + ":ignore",
)
_SKIP_DIRECTORIES: tuple[str, ...] = (
    "target/",
    "build/",
    ".gradle/",
    "vendor/",
)
_TOOL_NAMES: tuple[str, ...] = ("Checkstyle", "SpotBugs", "SonarQube")
_TOOL_DOCS_URLS: tuple[str, ...] = (
    "https://checkstyle.org/",
    "https://spotbugs.github.io/",
    "https://www.sonarsource.com/",
)


class JavaQaSuppressionStrategy:
    """QA suppression strategy for Java."""

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
        """Return acceptance tests for Java QA suppression strategy."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="Java QA suppression blocked",
                command=(
                    'Write file_path="/tmp/acceptance-test-qa-java/Example.java"'
                    ' content="@Suppress'
                    + "Warnings"
                    + '(\\"unchecked\\")\\npublic class Example {}"'
                ),
                description="Should block Java QA suppression annotation",
                expected_decision=Decision.DENY,
                expected_message_patterns=["suppression", "BLOCKED", "Java"],
                test_type=TestType.BLOCKING,
                safety_notes="Uses /tmp path - safe",
                setup_commands=["mkdir -p /tmp/acceptance-test-qa-java"],
                cleanup_commands=["rm -rf /tmp/acceptance-test-qa-java"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
