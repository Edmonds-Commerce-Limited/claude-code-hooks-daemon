"""Swift security strategy - dangerous API patterns (OWASP A03)."""

from typing import Any

from claude_code_hooks_daemon.strategies.security.protocol import SecurityPattern

_LANGUAGE_NAME = "Swift"
_EXTENSIONS: tuple[str, ...] = (".swift",)

_OWASP_CATEGORY = "A03"

_PATTERNS: tuple[SecurityPattern, ...] = (
    SecurityPattern(
        name="Process() - command injection risk",
        regex=r"\bProcess\s*\(\s*\)",
        owasp=_OWASP_CATEGORY,
        suggestion="Validate all arguments; use explicit argument arrays, not shell strings",
    ),
    SecurityPattern(
        name="evaluateJavaScript - XSS risk",
        regex=r"\bevaluateJavaScript\s*\(",
        owasp=_OWASP_CATEGORY,
        suggestion="Sanitize input before evaluating; use WKUserScript for trusted scripts",
    ),
    SecurityPattern(
        name="NSKeyedUnarchiver.unarchiveObject - object injection risk",
        regex=r"\bNSKeyedUnarchiver\.unarchiveObject\b",
        owasp=_OWASP_CATEGORY,
        suggestion="Use unarchivedObject(ofClass:from:) with explicit type validation",
    ),
)


class SwiftSecurityStrategy:
    """Detect Swift dangerous API patterns (OWASP A03).

    Catches Process(), evaluateJavaScript, and NSKeyedUnarchiver.unarchiveObject
    calls in Swift source files.
    """

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def extensions(self) -> tuple[str, ...]:
        return _EXTENSIONS

    @property
    def patterns(self) -> tuple[SecurityPattern, ...]:
        return _PATTERNS

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Swift security strategy."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="Block Swift Process() in source file",
                command=(
                    "Use the Write tool to write file_path='/workspace/src/test_security.swift' "
                    "with content 'let task = Process()'"
                ),
                description="Blocks writing Swift file with Process() call",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"SECURITY ANTIPATTERN BLOCKED",
                    r"Process\(\)",
                ],
                safety_notes="Handler blocks before file is written.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
