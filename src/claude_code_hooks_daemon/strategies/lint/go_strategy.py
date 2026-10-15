"""Go lint strategy implementation."""

import posixpath
import re
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.strategies.lint.common import COMMON_SKIP_PATHS
from claude_code_hooks_daemon.utils.scratch_dir import acceptance_path

# Language-specific constants
_LANGUAGE_NAME = "Go"
_EXTENSIONS: tuple[str, ...] = (".go",)
_DEFAULT_LINT_COMMAND = "go vet {file}"
_EXTENDED_LINT_COMMAND = "golangci-lint run {file}"
#: Acceptance-test fixture directory, below the gitignored acceptance root.
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
    # Every file in the package is excluded by a build tag (`//go:build ignore`,
    # a platform suffix), so there is nothing to vet: go exits 1 without a finding.
    "build constraints exclude all Go files",
)


#: ``gofmt -l -e`` lists unformatted files and exits 0 for them, so only a
#: syntax error (exit 2, every error reported) denies. Formatting is not a
#: deny: the repository's other languages do not deny on style at edit time
#: either (autofix owns formatting). Needs only the Go toolchain.
_PRECHECK_COMMANDS: tuple[str, ...] = ("gofmt -l -e {file}",)

#: A located finding: ``[vet: ]path.go:line:col: message``.
_FINDING = re.compile(r"^(?:vet: )?(?P<path>\S+?\.go):\d+:\d+: (?P<message>.*)$")

#: Type-check messages that mean a name or import is not (yet) resolved or
#: used, the state the first edit of a two-edit change leaves behind. go 1.19
#: says "undeclared name" / "imported but not used" / "declared but not used";
#: newer go says "undefined" / "imported and not used" / "declared and not used".
_UNRESOLVED_NAME = re.compile(
    r"^(?:undeclared name: |undefined: )"
    r"|imported (?:but|and) not used$"
    r"|declared (?:but|and) not used$"
)


def _is_edited_file(finding_path: str, edited: str) -> bool:
    """Whether a path in vet's output (relative to its cwd) names ``edited``."""
    normalized = posixpath.normpath(finding_path)
    edited_posix = Path(edited).as_posix()
    return edited_posix == normalized or edited_posix.endswith("/" + normalized)


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

    @property
    def precheck_lint_commands(self) -> tuple[str, ...]:
        return _PRECHECK_COMMANDS

    def is_mid_edit_output(self, output: str, file_path: str) -> bool:
        """Whether every `go vet` finding is expected while a change is half done.

        A finding is excused when it sits in a SIBLING file (this write did not
        cause it) or is the unresolved-name class on the edited file
        (``_UNRESOLVED_NAME``). One genuine finding on the edited file, or
        output with no located finding at all, is not excused.
        """
        findings = [m for line in output.splitlines() if (m := _FINDING.match(line.strip()))]
        if not findings:
            return False
        return all(
            not _is_edited_file(m["path"], file_path) or _UNRESOLVED_NAME.search(m["message"])
            for m in findings
        )

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
        from claude_code_hooks_daemon.constants import ToolName
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
            ToolPayload,
        )

        fixture_root = acceptance_path(_FIXTURE_DIR)
        probe_valid = ToolPayload(
            tool_name=ToolName.WRITE,
            tool_input={
                "file_path": acceptance_path(_FIXTURE_DIR, "valid.go"),
                "content": "package main\nfunc main() {}",
            },
        )
        probe_invalid = ToolPayload(
            tool_name=ToolName.WRITE,
            tool_input={
                "file_path": acceptance_path(_FIXTURE_DIR, "invalid.go"),
                "content": 'package main\nfunc main() {\n    x := "unclosed',
            },
        )

        return [
            AcceptanceTest(
                title="Go lint - valid code passes",
                command=probe_valid.as_instruction(),
                tool_payload=probe_valid,
                description="Valid Go code should pass lint validation",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes=(
                    "Inside the gitignored acceptance directory - safe. Creates temporary Go file."
                ),
                test_type=TestType.ADVISORY,
                setup_commands=[f"mkdir -p {fixture_root}"],
                cleanup_commands=[f"rm -rf {fixture_root}"],
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Go lint - invalid code blocked",
                command=probe_invalid.as_instruction(),
                tool_payload=probe_invalid,
                description="Invalid Go code (unclosed string) should be blocked",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"Go lint FAILED", r"invalid.go"],
                safety_notes=(
                    "Inside the gitignored acceptance directory - safe. "
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
