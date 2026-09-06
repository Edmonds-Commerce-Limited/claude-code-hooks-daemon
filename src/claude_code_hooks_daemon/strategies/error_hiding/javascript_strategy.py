"""JavaScript/TypeScript error-hiding strategy - patterns that suppress errors."""

from typing import Any

from claude_code_hooks_daemon.strategies.error_hiding.protocol import ErrorHidingPattern
from claude_code_hooks_daemon.utils.scratch_dir import scratch_path

_LANGUAGE_NAME = "JavaScript/TypeScript"
#: Acceptance-test fixture directory, below the sanctioned scratch root.
_FIXTURE_DIR = "acceptance-test-error-hiding-js"
_EXTENSIONS: tuple[str, ...] = (".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs")

_PATTERNS: tuple[ErrorHidingPattern, ...] = (
    ErrorHidingPattern(
        name="empty catch block",
        regex=r"catch\s*\([^)]*\)\s*\{\s*\}",
        example="catch (e) {}",
        suggestion="Log or handle the error; never swallow exceptions silently",
    ),
    ErrorHidingPattern(
        name="empty promise .catch",
        regex=r"\.catch\s*\(\s*(?:\(\)|[_a-zA-Z]\w*)\s*=>\s*\{\s*\}\s*\)",
        example=".catch(() => {})",
        suggestion="Handle promise rejections explicitly",
    ),
)


class JavaScriptErrorHidingStrategy:
    """Error-hiding strategy for JavaScript/TypeScript files."""

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
        """Return acceptance tests for JavaScript/TypeScript error-hiding strategy."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        fixture_root = scratch_path(_FIXTURE_DIR)

        return [
            AcceptanceTest(
                title="JavaScript: empty catch block swallows exceptions",
                command=(
                    "Write(\n"
                    f"  file_path='{scratch_path(_FIXTURE_DIR, 'bad.js')}',\n"
                    "  content='try { doSomething(); } catch (e) {}'\n"
                    ")"
                ),
                description=("Blocks JS file with empty catch block written via Write tool"),
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
                title="JavaScript: catch block with error handling is allowed",
                command=(
                    "Write(\n"
                    f"  file_path='{scratch_path(_FIXTURE_DIR, 'good.js')}',\n"
                    "  content='try { doSomething(); } "
                    "catch (e) { console.error(e); throw e; }'\n"
                    ")"
                ),
                description=("Allows JS file with proper catch block handling via Write tool"),
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
