"""Java error-hiding strategy - patterns that suppress errors in Java code."""

from typing import Any

from claude_code_hooks_daemon.strategies.error_hiding.protocol import ErrorHidingPattern
from claude_code_hooks_daemon.utils.scratch_dir import scratch_path

_LANGUAGE_NAME = "Java"
#: Acceptance-test fixture directory, below the sanctioned scratch root.
_FIXTURE_DIR = "acceptance-test-error-hiding-java"
_EXTENSIONS: tuple[str, ...] = (".java",)

_PATTERNS: tuple[ErrorHidingPattern, ...] = (
    ErrorHidingPattern(
        name="empty catch block",
        regex=r"catch\s*\(\s*\w[\w\s.<>?,]*\s*\w+\s*\)\s*\{\s*\}",
        example="catch (Exception e) {}",
        suggestion="Log or handle the exception; never swallow it silently",
    ),
)


class JavaErrorHidingStrategy:
    """Error-hiding strategy for Java source files (.java)."""

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def extensions(self) -> tuple[str, ...]:
        return _EXTENSIONS

    @property
    def patterns(self) -> tuple[ErrorHidingPattern, ...]:
        return _PATTERNS

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Java error-hiding strategy."""
        from claude_code_hooks_daemon.constants.tools import ToolName
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
            ToolPayload,
        )

        fixture_root = scratch_path(_FIXTURE_DIR)

        # Stated once; the prose is rendered from it (Plan 00345 Phase 2).
        # A WRITE payload, not Bash: these read as `Write(...)` call syntax,
        # and a Bash payload would probe a string no file-write handler
        # matches -- the deny test would then see ALLOW-by-not-matching and
        # pass while testing nothing.
        bad_probe = ToolPayload(
            tool_name=ToolName.WRITE,
            tool_input={
                "file_path": scratch_path(_FIXTURE_DIR, "Bad.java"),
                "content": "class Bad { void m() { try { } catch (Exception e) {} } }",
            },
        )
        good_probe = ToolPayload(
            tool_name=ToolName.WRITE,
            tool_input={
                "file_path": scratch_path(_FIXTURE_DIR, "Good.java"),
                "content": (
                    "class Good { void m() { try { } "
                    "catch (Exception e) { log.error(e.getMessage()); throw e; } } }"
                ),
            },
        )

        return [
            AcceptanceTest(
                title="Java: empty catch block swallows exception",
                command=bad_probe.as_instruction(),
                tool_payload=bad_probe,
                description=("Blocks Java file with empty catch block written via Write tool"),
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"BLOCKED \[R-ERROR-HIDING\]",
                    r"empty catch block",
                ],
                safety_notes="Inside the gitignored scratch directory - safe",
                test_type=TestType.BLOCKING,
                setup_commands=[f"mkdir -p {fixture_root}"],
                cleanup_commands=[f"rm -rf {fixture_root}"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Java: catch block with logging is allowed",
                command=good_probe.as_instruction(),
                tool_payload=good_probe,
                description=("Allows Java file with proper catch handling via Write tool"),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Inside the gitignored scratch directory - safe",
                test_type=TestType.ADVISORY,
                setup_commands=[f"mkdir -p {fixture_root}"],
                cleanup_commands=[f"rm -rf {fixture_root}"],
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]
