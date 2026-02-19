"""JavaScript/TypeScript error-hiding strategy - patterns that suppress errors."""

from typing import Any

from claude_code_hooks_daemon.strategies.error_hiding.protocol import ErrorHidingPattern

_LANGUAGE_NAME = "JavaScript/TypeScript"
_EXTENSIONS: tuple[str, ...] = (".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs")

_PATTERNS: tuple[ErrorHidingPattern, ...] = (
    ErrorHidingPattern(
        name="empty catch block",
        regex=r"catch\s*\([^)]*\)\s*\{\s*\}",
        example="catch (e) {}",
        suggestion="Log or handle the error; never swallow exceptions silently",
    ),
    ErrorHidingPattern(
        name="empty promise .catch",
        regex=r"\.catch\s*\(\s*(?:\(\)|[_a-zA-Z]\w*)\s*=>\s*\{\s*\}\s*\)",
        example=".catch(() => {})",
        suggestion="Handle promise rejections explicitly",
    ),
)


class JavaScriptErrorHidingStrategy:
    """Error-hiding strategy for JavaScript/TypeScript files."""

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
        """Return acceptance tests for JavaScript/TypeScript error-hiding strategy."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="JavaScript: empty catch block swallows exceptions",
                command=(
                    "Write(\n"
                    "  file_path='/tmp/acceptance-test-error-hiding/js/bad.js',\n"
                    "  content='try { doSomething(); } catch (e) {}'\n"
                    ")"
                ),
                description=("Blocks JS file with empty catch block written via Write tool"),
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
                title="JavaScript: catch block with error handling is allowed",
                command=(
                    "Write(\n"
                    "  file_path='/tmp/acceptance-test-error-hiding/js/good.js',\n"
                    "  content='try { doSomething(); } "
                    "catch (e) { console.error(e); throw e; }'\n"
                    ")"
                ),
                description=("Allows JS file with proper catch block handling via Write tool"),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Uses Write tool to a /tmp path",
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]
