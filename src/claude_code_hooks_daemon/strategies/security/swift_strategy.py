"""Swift security strategy - dangerous API patterns (OWASP A03)."""

from typing import Any

from claude_code_hooks_daemon.strategies.security.protocol import SecurityPattern
from claude_code_hooks_daemon.utils.scratch_dir import scratch_path

_LANGUAGE_NAME = "Swift"
#: Acceptance-test fixture directory, below the sanctioned scratch root.
_FIXTURE_DIR = "acceptance-test-security-swift"
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
        from claude_code_hooks_daemon.constants import ToolName
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
            ToolPayload,
        )

        process_probe = ToolPayload(
            tool_name=ToolName.WRITE,
            tool_input={
                "file_path": scratch_path(_FIXTURE_DIR, "test_security.swift"),
                "content": "let task = Process()",
            },
        )

        return [
            AcceptanceTest(
                title="Block Swift Process() in source file",
                command=process_probe.as_instruction(),
                tool_payload=process_probe,
                description="Blocks writing Swift file with Process() call",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"BLOCKED \[R-SEC-",
                    r"Process\(\)",
                ],
                safety_notes="Handler blocks before file is written.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
