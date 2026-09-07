"""Kotlin security strategy - dangerous API patterns (OWASP A03)."""

from typing import Any

from claude_code_hooks_daemon.strategies.security.protocol import SecurityPattern
from claude_code_hooks_daemon.utils.scratch_dir import scratch_path

_LANGUAGE_NAME = "Kotlin"
#: Acceptance-test fixture directory, below the sanctioned scratch root.
_FIXTURE_DIR = "acceptance-test-security-kotlin"
_EXTENSIONS: tuple[str, ...] = (".kt", ".kts")

_OWASP_CATEGORY = "A03"

_PATTERNS: tuple[SecurityPattern, ...] = (
    SecurityPattern(
        name="Runtime.getRuntime().exec() - command injection risk",
        regex=r"Runtime\.getRuntime\(\)\.exec\s*\(",
        owasp=_OWASP_CATEGORY,
        suggestion="Use ProcessBuilder with explicit argument lists",
    ),
    SecurityPattern(
        name="ObjectInputStream() - unsafe deserialization risk",
        regex=r"\bObjectInputStream\s*\(",
        owasp=_OWASP_CATEGORY,
        suggestion="Use safe serialization (kotlinx.serialization, JSON)",
    ),
    SecurityPattern(
        name="XMLDecoder() - unsafe XML deserialization risk",
        regex=r"\bXMLDecoder\s*\(",
        owasp=_OWASP_CATEGORY,
        suggestion="Use safe XML parsing (kotlinx.serialization, Jackson)",
    ),
    SecurityPattern(
        name="ScriptEngineManager - dynamic script execution risk",
        regex=r"\bScriptEngineManager\b",
        owasp=_OWASP_CATEGORY,
        suggestion="Avoid javax.script for untrusted input; use compiled code",
    ),
)


class KotlinSecurityStrategy:
    """Detect Kotlin dangerous API patterns (OWASP A03).

    Catches Runtime.exec, ObjectInputStream, XMLDecoder, and ScriptEngineManager
    usage in Kotlin source files (.kt and .kts).
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
        """Return acceptance tests for Kotlin security strategy."""
        from claude_code_hooks_daemon.constants import ToolName
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
            ToolPayload,
        )

        object_input_stream_probe = ToolPayload(
            tool_name=ToolName.WRITE,
            tool_input={
                "file_path": str(scratch_path(_FIXTURE_DIR, "test_security.kt")),
                "content": "val ois = ObjectInputStream(socket.getInputStream())",
            },
        )

        return [
            AcceptanceTest(
                title="Block Kotlin ObjectInputStream in source file",
                command=object_input_stream_probe.as_instruction(),
                tool_payload=object_input_stream_probe,
                description="Blocks writing Kotlin file with ObjectInputStream() call",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"BLOCKED \[R-SEC-",
                    r"ObjectInputStream",
                ],
                safety_notes="Handler blocks before file is written.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
