"""JavaScript/TypeScript QA suppression strategy implementation."""

from typing import Any

# ── Language-specific constants ──────────────────────────────────
_LANGUAGE_NAME = "JavaScript/TypeScript"
_EXTENSIONS: tuple[str, ...] = (".js", ".jsx", ".ts", ".tsx")
_FORBIDDEN_PATTERNS: tuple[str, ...] = (
    r"//\s*eslint-" + "disable",
    r"/\*\s*eslint-" + "disable",
    r"@ts-" + "ignore",
    r"@ts-" + "expect-error",
    r"@ts-" + "nocheck",
    r"//\s*no" + "inspection",
)
_SKIP_DIRECTORIES: tuple[str, ...] = (
    "node_modules/",
    "dist/",
    "build/",
    ".next/",
    "coverage/",
)
_TOOL_NAMES: tuple[str, ...] = ("ESLint", "TypeScript", "Prettier")
_TOOL_DOCS_URLS: tuple[str, ...] = (
    "https://eslint.org/",
    "https://www.typescriptlang.org/",
    "https://prettier.io/",
)


class JavaScriptQaSuppressionStrategy:
    """QA suppression strategy for JavaScript/TypeScript."""

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
        """Return acceptance tests for JavaScript/TypeScript QA suppression strategy."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="JavaScript/TypeScript QA suppression blocked",
                command=(
                    'Write file_path="/tmp/acceptance-test-qa-js/example.ts"'
                    ' content="// eslint-' + "disable" + ' no-console\\nconst x = 1;"'
                ),
                description="Should block JavaScript/TypeScript QA suppression comment",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    "suppression",
                    "BLOCKED",
                    "JavaScript/TypeScript",
                ],
                test_type=TestType.BLOCKING,
                safety_notes="Uses /tmp path - safe",
                setup_commands=["mkdir -p /tmp/acceptance-test-qa-js"],
                cleanup_commands=["rm -rf /tmp/acceptance-test-qa-js"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
