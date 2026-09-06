"""Go lint strategy implementation."""

from typing import Any

from claude_code_hooks_daemon.strategies.lint.common import COMMON_SKIP_PATHS
from claude_code_hooks_daemon.utils.scratch_dir import scratch_path

# Language-specific constants
_LANGUAGE_NAME = "Go"
_EXTENSIONS: tuple[str, ...] = (".go",)
_DEFAULT_LINT_COMMAND = "go vet {file}"
_EXTENDED_LINT_COMMAND = "golangci-lint run {file}"
#: Acceptance-test fixture directory, below the sanctioned scratch root.
_FIXTURE_DIR = "acceptance-test-lint-go"
# `go vet` resolves PACKAGES, so it needs a module. In a repository with no
# `go.mod` -- any polyglot repo that merely contains a `.go` file -- it exits
# non-zero with one of these before reading the file at all. That is the
# launcher reporting it cannot analyse here, not a finding about the file's
# content: `go vet <file>` on the same file exits 0. Treating it as a lint
# failure DENIES valid Go, which is the false positive this recognises.
_MODULE_CONTEXT_MARKERS: tuple[str, ...] = (
    "cannot find main module",
    "go.mod file not found",
)


class GoLintStrategy:
    """Lint enforcement strategy for Go files.

    Default: go vet (static analysis)
    Extended: golangci-lint (comprehensive linting)
    """

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def extensions(self) -> tuple[str, ...]:
        return _EXTENSIONS

    @property
    def default_lint_command(self) -> str:
        return _DEFAULT_LINT_COMMAND

    @property
    def extended_lint_command(self) -> str | None:
        return _EXTENDED_LINT_COMMAND

    @property
    def skip_paths(self) -> tuple[str, ...]:
        return COMMON_SKIP_PATHS

    def is_tool_unavailable_output(self, output: str) -> bool:
        """Recognise `go vet` failing for want of a module rather than for code.

        See ``_MODULE_CONTEXT_MARKERS``. `go` is on PATH and runs, so the
        handler's usual "tool absent" signal (FileNotFoundError) never fires,
        yet the non-zero exit says nothing about the file -- it never got that
        far. Degrading to an advisory ALLOW keeps a valid `.go` file writable
        in a repository that is not a Go module, while a real vet finding or a
        syntax error still denies.
        """
        return any(marker in output for marker in _MODULE_CONTEXT_MARKERS)

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Go lint strategy."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        fixture_root = scratch_path(_FIXTURE_DIR)

        return [
            AcceptanceTest(
                title="Go lint - valid code passes",
                command=(
                    "Use the Write tool to create file "
                    f"{scratch_path(_FIXTURE_DIR, 'valid.go')} "
                    'with content "package main\\nfunc main() {}"'
                ),
                description="Valid Go code should pass lint validation",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes=(
                    "Inside the gitignored scratch directory - safe. Creates temporary Go file."
                ),
                test_type=TestType.ADVISORY,
                setup_commands=[f"mkdir -p {fixture_root}"],
                cleanup_commands=[f"rm -rf {fixture_root}"],
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Go lint - invalid code blocked",
                command=(
                    "Use the Write tool to create file "
                    f"{scratch_path(_FIXTURE_DIR, 'invalid.go')} "
                    'with content "package main\\nfunc main() {\\n    x := \\"unclosed"'
                ),
                description="Invalid Go code (unclosed string) should be blocked",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"Go lint FAILED", r"invalid.go"],
                safety_notes=(
                    "Inside the gitignored scratch directory - safe. "
                    "Creates temporary Go file with syntax error."
                ),
                test_type=TestType.BLOCKING,
                required_tools=["go"],
                setup_commands=[f"mkdir -p {fixture_root}"],
                cleanup_commands=[f"rm -rf {fixture_root}"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
