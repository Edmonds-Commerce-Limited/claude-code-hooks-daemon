"""Dart security strategy - dangerous API patterns (OWASP A03)."""

from typing import Any

from claude_code_hooks_daemon.strategies.security.protocol import SecurityPattern

_LANGUAGE_NAME = "Dart"
_EXTENSIONS: tuple[str, ...] = (".dart",)

_OWASP_CATEGORY = "A03"

_PATTERNS: tuple[SecurityPattern, ...] = (
    SecurityPattern(
        name="Process.run() - command injection risk",
        regex=r"\bProcess\.run\s*\(",
        owasp=_OWASP_CATEGORY,
        suggestion="Validate all arguments; never pass unsanitized user input",
    ),
    SecurityPattern(
        name="Process.start() - command injection risk",
        regex=r"\bProcess\.start\s*\(",
        owasp=_OWASP_CATEGORY,
        suggestion="Validate all arguments; never pass unsanitized user input",
    ),
    SecurityPattern(
        name=".innerHTML = - XSS risk",
        regex=r"\.innerHTML\s*=",
        owasp=_OWASP_CATEGORY,
        suggestion="Use .text or element.setInnerHtml() with NodeTreeSanitizer",
    ),
)


class DartSecurityStrategy:
    """Detect Dart dangerous API patterns (OWASP A03).

    Catches Process.run(), Process.start(), and .innerHTML = assignments
    in Dart source files.
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
        """Return acceptance tests for Dart security strategy."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="Block Dart Process.run() in source file",
                command=(
                    "Use the Write tool to write file_path='/workspace/src/test_security.dart' "
                    "with content \"await Process.run('ls', ['-la']);\""
                ),
                description="Blocks writing Dart file with Process.run() call",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"SECURITY ANTIPATTERN BLOCKED",
                    r"Process\.run\(\)",
                ],
                safety_notes="Handler blocks before file is written.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
