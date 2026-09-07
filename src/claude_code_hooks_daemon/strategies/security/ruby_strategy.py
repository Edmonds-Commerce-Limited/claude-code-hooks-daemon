"""Ruby security strategy - dangerous function patterns (OWASP A03)."""

from typing import Any

from claude_code_hooks_daemon.strategies.security.protocol import SecurityPattern
from claude_code_hooks_daemon.utils.scratch_dir import scratch_path

_LANGUAGE_NAME = "Ruby"
#: Acceptance-test fixture directory, below the sanctioned scratch root.
_FIXTURE_DIR = "acceptance-test-security-ruby"
_EXTENSIONS: tuple[str, ...] = (".rb",)

_OWASP_CATEGORY = "A03"

_PATTERNS: tuple[SecurityPattern, ...] = (
    SecurityPattern(
        name="eval() - code injection risk",
        regex=r"\beval\s*[\s(]",
        owasp=_OWASP_CATEGORY,
        suggestion="Avoid dynamic code evaluation; use safe alternatives",
    ),
    SecurityPattern(
        name="system() - command injection risk",
        regex=r"\bsystem\s*\(",
        owasp=_OWASP_CATEGORY,
        suggestion="Use Open3.capture3 with explicit argument lists",
    ),
    SecurityPattern(
        name="exec() - command injection risk",
        regex=r"\bexec\s*\(",
        owasp=_OWASP_CATEGORY,
        suggestion="Use Open3.capture3 with explicit argument lists",
    ),
    SecurityPattern(
        name="instance_eval - code injection risk",
        regex=r"\binstance_eval\b",
        owasp=_OWASP_CATEGORY,
        suggestion="Avoid dynamic code evaluation; use safe alternatives",
    ),
    SecurityPattern(
        name="class_eval - code injection risk",
        regex=r"\bclass_eval\b",
        owasp=_OWASP_CATEGORY,
        suggestion="Avoid dynamic code evaluation; use safe alternatives",
    ),
    SecurityPattern(
        name="Marshal.load - deserialization injection risk",
        regex=r"\bMarshal\.load\b",
        owasp=_OWASP_CATEGORY,
        suggestion="Use JSON.parse for safe deserialization",
    ),
    SecurityPattern(
        name="IO.popen - command injection risk",
        regex=r"\bIO\.popen\b",
        owasp=_OWASP_CATEGORY,
        suggestion="Use Open3.capture3 with explicit argument lists",
    ),
)


class RubySecurityStrategy:
    """Detect Ruby dangerous function patterns (OWASP A03).

    Catches eval, system, exec, instance_eval, class_eval, Marshal.load,
    and IO.popen calls in Ruby source files.
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
        """Return acceptance tests for Ruby security strategy."""
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
                "file_path": str(scratch_path(_FIXTURE_DIR, "test_security.rb")),
                "content": "eval(user_input)",
            },
        )

        return [
            AcceptanceTest(
                title="Block Ruby eval in source file",
                command=eval_probe.as_instruction(),
                tool_payload=eval_probe,
                description="Blocks writing Ruby file with eval() call",
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
