"""PHP security strategy - dangerous function patterns (OWASP A03)."""

from typing import Any

from claude_code_hooks_daemon.strategies.security.protocol import SecurityPattern
from claude_code_hooks_daemon.utils.scratch_dir import scratch_path

_LANGUAGE_NAME = "PHP"
#: Acceptance-test fixture directory, below the sanctioned scratch root.
_FIXTURE_DIR = "acceptance-test-security-php"
_EXTENSIONS: tuple[str, ...] = (".php",)

_OWASP_CATEGORY = "A03"

_PATTERNS: tuple[SecurityPattern, ...] = (
    SecurityPattern(
        name="eval() - code injection risk",
        regex=r"\beval\s*\(",
        owasp=_OWASP_CATEGORY,
        suggestion="Use safe alternatives (e.g. Symfony ExpressionLanguage)",
    ),
    SecurityPattern(
        name="exec() - command injection risk",
        regex=r"\bexec\s*\(",
        owasp=_OWASP_CATEGORY,
        suggestion="Use Symfony Process component with explicit arguments",
    ),
    SecurityPattern(
        name="shell_exec() - command injection risk",
        regex=r"\bshell_exec\s*\(",
        owasp=_OWASP_CATEGORY,
        suggestion="Use Symfony Process component with explicit arguments",
    ),
    SecurityPattern(
        name="system() - command injection risk",
        regex=r"\bsystem\s*\(",
        owasp=_OWASP_CATEGORY,
        suggestion="Use Symfony Process component with explicit arguments",
    ),
    SecurityPattern(
        name="passthru() - command injection risk",
        regex=r"\bpassthru\s*\(",
        owasp=_OWASP_CATEGORY,
        suggestion="Use Symfony Process component with explicit arguments",
    ),
    SecurityPattern(
        name="proc_open() - command injection risk",
        regex=r"\bproc_open\s*\(",
        owasp=_OWASP_CATEGORY,
        suggestion="Use Symfony Process component with explicit arguments",
    ),
    SecurityPattern(
        name="unserialize() - object injection risk",
        regex=r"\bunserialize\s*\(",
        owasp=_OWASP_CATEGORY,
        suggestion="Use json_decode() instead",
    ),
)


class PhpSecurityStrategy:
    """Detect PHP dangerous function patterns (OWASP A03).

    Catches eval, exec, shell_exec, system, passthru, proc_open,
    and unserialize calls in PHP source files.
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
        """Return acceptance tests for PHP security strategy."""
        from claude_code_hooks_daemon.constants import ToolName
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
            ToolPayload,
        )

        eval_probe = ToolPayload(
            tool_name=ToolName.WRITE,
            tool_input={
                "file_path": scratch_path(_FIXTURE_DIR, "test_security.php"),
                "content": "<?php eval($userInput);",
            },
        )

        return [
            AcceptanceTest(
                title="Block PHP eval in source file",
                command=eval_probe.as_instruction(),
                tool_payload=eval_probe,
                description="Blocks writing PHP file with eval() call",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"BLOCKED \[R-SEC-",
                    r"eval\(\)",
                ],
                safety_notes="Handler blocks before file is written.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
