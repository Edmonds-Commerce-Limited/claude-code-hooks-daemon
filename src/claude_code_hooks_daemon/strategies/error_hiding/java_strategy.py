"""Java error-hiding strategy - patterns that suppress errors in Java code."""

from typing import Any

from claude_code_hooks_daemon.strategies.error_hiding.protocol import ErrorHidingPattern

_LANGUAGE_NAME = "Java"
_EXTENSIONS: tuple[str, ...] = (".java",)

_PATTERNS: tuple[ErrorHidingPattern, ...] = (
    ErrorHidingPattern(
        name="empty catch block",
        regex=r"catch\s*\(\s*\w[\w\s.<>?,]*\s*\w+\s*\)\s*\{\s*\}",
        example="catch (Exception e) {}",
        suggestion="Log or handle the exception; never swallow it silently",
    ),
)


class JavaErrorHidingStrategy:
    """Error-hiding strategy for Java source files (.java)."""

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
        """Return acceptance tests for Java error-hiding strategy."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="Java: empty catch block swallows exception",
                command=(
                    "Write(\n"
                    "  file_path='/tmp/acceptance-test-error-hiding/java/Bad.java',\n"
                    "  content='class Bad { void m() { try { } catch (Exception e) {} } }'\n"
                    ")"
                ),
                description=("Blocks Java file with empty catch block written via Write tool"),
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"Error-hiding pattern detected",
                    r"empty catch block",
                ],
                safety_notes="Uses Write tool to a /tmp path",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Java: catch block with logging is allowed",
                command=(
                    "Write(\n"
                    "  file_path='/tmp/acceptance-test-error-hiding/java/Good.java',\n"
                    "  content='class Good { void m() { try { } "
                    "catch (Exception e) { log.error(e.getMessage()); throw e; } } }'\n"
                    ")"
                ),
                description=("Allows Java file with proper catch handling via Write tool"),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Uses Write tool to a /tmp path",
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]
