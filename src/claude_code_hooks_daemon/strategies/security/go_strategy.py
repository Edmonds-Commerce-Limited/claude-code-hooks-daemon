"""Go security strategy - dangerous template type conversion patterns (OWASP A03)."""

from typing import Any

from claude_code_hooks_daemon.strategies.security.protocol import SecurityPattern

_LANGUAGE_NAME = "Go"
_EXTENSIONS: tuple[str, ...] = (".go",)

_OWASP_CATEGORY = "A03"

_PATTERNS: tuple[SecurityPattern, ...] = (
    SecurityPattern(
        name="template.HTML() - XSS injection risk",
        regex=r"\btemplate\.HTML\s*\(",
        owasp=_OWASP_CATEGORY,
        suggestion="Use template auto-escaping; never mark raw strings as safe HTML",
    ),
    SecurityPattern(
        name="template.JS() - XSS injection risk",
        regex=r"\btemplate\.JS\s*\(",
        owasp=_OWASP_CATEGORY,
        suggestion="Use template auto-escaping; never mark raw strings as safe JS",
    ),
    SecurityPattern(
        name="template.URL() - open redirect / XSS risk",
        regex=r"\btemplate\.URL\s*\(",
        owasp=_OWASP_CATEGORY,
        suggestion="Use template auto-escaping; never mark raw strings as safe URLs",
    ),
)


class GoSecurityStrategy:
    """Detect Go dangerous template type conversion patterns (OWASP A03).

    Catches template.HTML(), template.JS(), and template.URL() calls that
    bypass Go's html/template auto-escaping in Go source files.
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
        """Return acceptance tests for Go security strategy."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="Block Go template.HTML() in source file",
                command=(
                    "Use the Write tool to write file_path='/workspace/src/test_security.go' "
                    "with content 'safe := template.HTML(userInput)'"
                ),
                description="Blocks writing Go file with template.HTML() call",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"SECURITY ANTIPATTERN BLOCKED",
                    r"template\.HTML\(\)",
                ],
                safety_notes="Handler blocks before file is written.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
