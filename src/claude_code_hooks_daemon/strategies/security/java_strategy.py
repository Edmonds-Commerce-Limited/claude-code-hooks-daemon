"""Java security strategy - dangerous API patterns (OWASP A03)."""

from typing import Any

from claude_code_hooks_daemon.strategies.security.protocol import SecurityPattern

_LANGUAGE_NAME = "Java"
_EXTENSIONS: tuple[str, ...] = (".java",)

_OWASP_CATEGORY = "A03"

_PATTERNS: tuple[SecurityPattern, ...] = (
    SecurityPattern(
        name="Runtime.getRuntime().exec() - command injection risk",
        regex=r"Runtime\.getRuntime\(\)\.exec\s*\(",
        owasp=_OWASP_CATEGORY,
        suggestion="Use ProcessBuilder with explicit argument lists",
    ),
    SecurityPattern(
        name="new ObjectInputStream - unsafe deserialization risk",
        regex=r"\bnew\s+ObjectInputStream\b",
        owasp=_OWASP_CATEGORY,
        suggestion="Use safe serialization (JSON, Protocol Buffers); validate before deserialization",
    ),
    SecurityPattern(
        name="new XMLDecoder - unsafe XML deserialization risk",
        regex=r"\bnew\s+XMLDecoder\b",
        owasp=_OWASP_CATEGORY,
        suggestion="Use safe XML parsing (JAXB, Jackson); never deserialize untrusted XML",
    ),
    SecurityPattern(
        name="ScriptEngineManager - dynamic script execution risk",
        regex=r"\bScriptEngineManager\b",
        owasp=_OWASP_CATEGORY,
        suggestion="Avoid javax.script for untrusted input; use compiled code",
    ),
)


class JavaSecurityStrategy:
    """Detect Java dangerous API patterns (OWASP A03).

    Catches Runtime.exec, ObjectInputStream, XMLDecoder, and ScriptEngineManager
    usage in Java source files.
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
        """Return acceptance tests for Java security strategy."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="Block Java Runtime.exec() in source file",
                command=(
                    "Use the Write tool to write file_path='/workspace/src/test_security.java' "
                    "with content 'Runtime.getRuntime().exec(userInput);'"
                ),
                description="Blocks writing Java file with Runtime.getRuntime().exec() call",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"SECURITY ANTIPATTERN BLOCKED",
                    r"Runtime\.getRuntime",
                ],
                safety_notes="Handler blocks before file is written.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
