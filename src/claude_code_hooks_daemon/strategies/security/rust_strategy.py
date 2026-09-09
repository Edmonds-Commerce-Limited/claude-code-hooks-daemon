"""Rust security strategy - unsafe FFI boundary patterns (OWASP A03)."""

from typing import Any

from claude_code_hooks_daemon.strategies.security.protocol import SecurityPattern
from claude_code_hooks_daemon.utils.scratch_dir import scratch_path

_LANGUAGE_NAME = "Rust"
#: Acceptance-test fixture directory, below the sanctioned scratch root.
_FIXTURE_DIR = "acceptance-test-security-rust"
_EXTENSIONS: tuple[str, ...] = (".rs",)

_OWASP_CATEGORY = "A03"

_PATTERNS: tuple[SecurityPattern, ...] = (
    SecurityPattern(
        name="from_raw_parts - unsafe pointer dereference",
        regex=r"\bfrom_raw_parts\b",
        owasp=_OWASP_CATEGORY,
        suggestion="Ensure raw pointer is valid and lifetime is correct; prefer safe slice operations",
    ),
    SecurityPattern(
        name="transmute - type safety bypass",
        regex=r"\btransmute\b",
        owasp=_OWASP_CATEGORY,
        suggestion="Use safe conversion methods (as, From/Into traits); transmute bypasses type safety",
    ),
)


class RustSecurityStrategy:
    """Detect Rust dangerous unsafe FFI patterns (OWASP A03).

    Catches from_raw_parts and transmute calls in Rust source files.
    Note: std::process::Command is the correct way to run processes in Rust
    and is intentionally NOT flagged.
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
        """Return acceptance tests for Rust security strategy."""
        from claude_code_hooks_daemon.constants import ToolName
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
            ToolPayload,
        )

        transmute_probe = ToolPayload(
            tool_name=ToolName.WRITE,
            tool_input={
                "file_path": scratch_path(_FIXTURE_DIR, "test_security.rs"),
                "content": "let x: u32 = std::mem::transmute(y);",
            },
        )

        return [
            AcceptanceTest(
                title="Block Rust transmute in source file",
                command=transmute_probe.as_instruction(),
                tool_payload=transmute_probe,
                description="Blocks writing Rust file with transmute call",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"BLOCKED \[R-SEC-",
                    r"transmute",
                ],
                safety_notes="Handler blocks before file is written.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
