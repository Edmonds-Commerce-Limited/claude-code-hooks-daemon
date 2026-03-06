"""JavaScript/TypeScript security strategy - unsafe DOM and eval patterns (OWASP A03)."""

from typing import Any

from claude_code_hooks_daemon.strategies.security.protocol import SecurityPattern

_LANGUAGE_NAME = "JavaScript"
_EXTENSIONS: tuple[str, ...] = (".ts", ".tsx", ".js", ".jsx")

_OWASP_CATEGORY = "A03"

_PATTERNS: tuple[SecurityPattern, ...] = (
    SecurityPattern(
        name="eval() - code injection risk",
        regex=r"\beval\s*\(",
        owasp=_OWASP_CATEGORY,
        suggestion="Use JSON.parse() for data, or a safe expression evaluator",
    ),
    SecurityPattern(
        name="new Function() - code injection risk",
        regex=r"\bnew\s+Function\s*\(",
        owasp=_OWASP_CATEGORY,
        suggestion="Use JSON.parse() for data, or a safe expression evaluator",
    ),
    SecurityPattern(
        name="dangerouslySetInnerHTML - XSS risk",
        regex=r"dangerouslySetInnerHTML",
        owasp=_OWASP_CATEGORY,
        suggestion="Use React JSX or sanitise input with DOMPurify",
    ),
    SecurityPattern(
        name="innerHTML assignment - XSS risk",
        regex=r"\.innerHTML\s*=",
        owasp=_OWASP_CATEGORY,
        suggestion="Use textContent or sanitise input with DOMPurify",
    ),
    SecurityPattern(
        name="document.write() - XSS risk",
        regex=r"\bdocument\.write\s*\(",
        owasp=_OWASP_CATEGORY,
        suggestion="Use DOM manipulation methods (createElement, appendChild)",
    ),
)


class JavaScriptSecurityStrategy:
    """Detect JavaScript/TypeScript unsafe patterns (OWASP A03).

    Catches eval, new Function, dangerouslySetInnerHTML, innerHTML
    assignment, and document.write in JS/TS source files.
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
        """Return acceptance tests for JavaScript security strategy."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="Block JS eval in source file",
                command=(
                    "Use the Write tool to write file_path='/workspace/src/utils.ts' "
                    "with content 'const result = eval(userCode);'"
                ),
                description="Blocks writing TS file with eval() call",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"SECURITY ANTIPATTERN BLOCKED",
                    r"eval\(\)",
                ],
                safety_notes="Handler blocks before file is written.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
