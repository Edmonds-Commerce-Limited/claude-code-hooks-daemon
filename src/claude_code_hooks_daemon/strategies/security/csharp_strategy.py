"""C# security strategy - dangerous API patterns (OWASP A03)."""

from typing import Any

from claude_code_hooks_daemon.strategies.security.protocol import SecurityPattern
from claude_code_hooks_daemon.utils.scratch_dir import scratch_path

_LANGUAGE_NAME = "C#"
#: Acceptance-test fixture directory, below the sanctioned scratch root.
_FIXTURE_DIR = "acceptance-test-security-csharp"
_EXTENSIONS: tuple[str, ...] = (".cs",)

_OWASP_CATEGORY = "A03"

_PATTERNS: tuple[SecurityPattern, ...] = (
    SecurityPattern(
        name="Process.Start() - command injection risk",
        regex=r"\bProcess\.Start\s*\(",
        owasp=_OWASP_CATEGORY,
        suggestion="Use ProcessStartInfo with explicit arguments, never shell commands",
    ),
    SecurityPattern(
        name="BinaryFormatter - unsafe deserialization risk",
        regex=r"\bBinaryFormatter\b",
        owasp=_OWASP_CATEGORY,
        suggestion="Use System.Text.Json or JsonSerializer; BinaryFormatter is obsolete and unsafe",
    ),
    SecurityPattern(
        name="LosFormatter - unsafe deserialization risk",
        regex=r"\bLosFormatter\b",
        owasp=_OWASP_CATEGORY,
        suggestion="Use System.Text.Json for serialization",
    ),
    SecurityPattern(
        name="ObjectStateFormatter - unsafe deserialization risk",
        regex=r"\bObjectStateFormatter\b",
        owasp=_OWASP_CATEGORY,
        suggestion="Use System.Text.Json for serialization",
    ),
)


class CSharpSecurityStrategy:
    """Detect C# dangerous API patterns (OWASP A03).

    Catches Process.Start, BinaryFormatter, LosFormatter, and ObjectStateFormatter
    usage in C# source files.
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
        """Return acceptance tests for C# security strategy."""
        from claude_code_hooks_daemon.constants import ToolName
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
            ToolPayload,
        )

        binary_formatter_probe = ToolPayload(
            tool_name=ToolName.WRITE,
            tool_input={
                "file_path": scratch_path(_FIXTURE_DIR, "test_security.cs"),
                "content": "BinaryFormatter formatter = new BinaryFormatter();",
            },
        )

        return [
            AcceptanceTest(
                title="Block C# BinaryFormatter in source file",
                command=binary_formatter_probe.as_instruction(),
                tool_payload=binary_formatter_probe,
                description="Blocks writing C# file with BinaryFormatter usage",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"BLOCKED \[R-SEC-",
                    r"BinaryFormatter",
                ],
                safety_notes="Handler blocks before file is written.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
