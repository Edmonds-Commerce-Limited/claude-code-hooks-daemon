"""Go TDD strategy implementation."""

import re
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.strategies.tdd.common import (
    has_ancestor_marker,
    is_in_common_test_directory,
    matches_directory,
)
from claude_code_hooks_daemon.utils.path_predicates import path_is_dir
from claude_code_hooks_daemon.utils.scratch_dir import acceptance_path

# Language-specific constants
_LANGUAGE_NAME = "Go"
#: Acceptance-test fixture directory, below the gitignored acceptance root.
_FIXTURE_DIR = "acceptance-test-tdd-go"
_EXTENSIONS: tuple[str, ...] = (".go",)
_SKIP_DIRECTORIES: tuple[str, ...] = ("vendor/", "testdata/")
_TEST_SUFFIX = "_test.go"
_MODULE_MARKER = "go.mod"
_GENERATED_SUFFIXES: tuple[str, ...] = (".pb.go", "_gen.go")
_GENERATED_PREFIX = "zz_generated"
_DOC_FILE = "doc.go"
_MAIN_FILE = "main.go"
_CMD_DIR = "cmd"
_PACKAGE_CLAUSE = "package "
#: Go's own convention for marking generated code (golang.org/s/generatedcode).
_GENERATED_HEADER = re.compile(r"^// Code generated .* DO NOT EDIT\.$")


def _has_generated_header(content: str) -> bool:
    """Whether a line before the package clause is Go's "Code generated" marker."""
    for line in content.splitlines():
        if line.startswith(_PACKAGE_CLAUSE):
            return False
        if _GENERATED_HEADER.match(line.rstrip()):
            return True
    return False


def _package_has_tests(package_dir: Path) -> bool:
    """Whether the package directory already holds any ``*_test.go`` file.

    Go tests per package, not per file. A directory the daemon cannot list is
    reported as having no tests (``Path.glob`` yields nothing for it), so the
    gate stays on rather than silently off.
    """
    if not path_is_dir(package_dir, unreadable_means=False):
        return False
    return any(package_dir.glob(f"*{_TEST_SUFFIX}"))


class GoTddStrategy:
    """TDD enforcement strategy for Go projects.

    Go tests per package: a new file in a package that already has any
    ``*_test.go`` passes; otherwise ``server.go`` wants ``server_test.go``.
    Enforced for any .go file inside a module (a go.mod at or above it);
    generated files, ``doc.go`` and ``cmd/<name>/main.go`` are exempt.
    """

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def extensions(self) -> tuple[str, ...]:
        return _EXTENSIONS

    def is_test_file(self, file_path: str) -> bool:
        if is_in_common_test_directory(file_path):
            return True

        # Go test files end with "_test.go"
        return file_path.endswith(_TEST_SUFFIX)

    def is_production_source(self, file_path: str) -> bool:
        """Any .go file inside a Go module, whatever its directory."""
        return has_ancestor_marker(file_path, _MODULE_MARKER)

    def is_excluded_source_file(self, file_path: str) -> bool:
        """Generated files by name, ``doc.go`` and ``cmd/<name>/main.go``."""
        path = Path(file_path)
        name = path.name
        if name.endswith(_GENERATED_SUFFIXES) or name.startswith(_GENERATED_PREFIX):
            return True
        if name == _DOC_FILE:
            return True
        return name == _MAIN_FILE and path.parent.parent.name == _CMD_DIR

    def should_skip(self, file_path: str, content: str = "") -> bool:
        """Vendored/testdata files, generated files, and packages that already have tests."""
        if matches_directory(file_path, _SKIP_DIRECTORIES):
            return True
        if _has_generated_header(content):
            return True
        return _package_has_tests(Path(file_path).parent)

    def compute_test_filename(self, source_filename: str) -> str:
        basename = Path(source_filename).stem
        return f"{basename}_test.go"

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Go TDD strategy."""

        from claude_code_hooks_daemon.constants import ToolName
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
            ToolPayload,
        )

        fixture_root = acceptance_path(_FIXTURE_DIR)
        # Stated ONCE, and the prose is rendered from it (Plan 00243). The
        # payload is what a harness dispatches; `as_instruction()` is what a
        # human tester reads. Hand-writing both is what let five grammars and
        # a drifting path into the same field.
        probe = ToolPayload(
            tool_name=ToolName.WRITE,
            tool_input={
                "file_path": acceptance_path(_FIXTURE_DIR, "src", "myapp", "server.go"),
                "content": "package main\n\nfunc main() {}",
            },
        )

        return [
            AcceptanceTest(
                title="TDD enforcement for Go source file",
                command=probe.as_instruction(),
                tool_payload=probe,
                description="Blocks Go source file creation without corresponding test file",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"BLOCKED \[R-TDD-TEST-FIRST\]", r"Go", r"test file"],
                safety_notes=(
                    "Inside the gitignored acceptance directory - safe. Handler blocks "
                    "Write before file is created."
                ),
                test_type=TestType.BLOCKING,
                setup_commands=[
                    f"mkdir -p {fixture_root}/src/myapp",
                    f"printf 'module example.com/probe\\n' > {fixture_root}/go.mod",
                ],
                cleanup_commands=[f"rm -rf {fixture_root}"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
