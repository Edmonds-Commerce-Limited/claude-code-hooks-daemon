"""Tests for Go lint strategy."""

import pytest

from claude_code_hooks_daemon.strategies.lint.go_strategy import GoLintStrategy
from claude_code_hooks_daemon.strategies.lint.protocol import LintStrategy


@pytest.fixture()
def strategy() -> GoLintStrategy:
    return GoLintStrategy()


class TestProtocolConformance:
    def test_implements_protocol(self, strategy: GoLintStrategy) -> None:
        assert isinstance(strategy, LintStrategy)


class TestProperties:
    def test_language_name(self, strategy: GoLintStrategy) -> None:
        assert strategy.language_name == "Go"

    def test_extensions(self, strategy: GoLintStrategy) -> None:
        assert strategy.extensions == (".go",)

    def test_default_lint_command(self, strategy: GoLintStrategy) -> None:
        assert strategy.default_lint_command == "go vet {file}"

    def test_extended_lint_command(self, strategy: GoLintStrategy) -> None:
        assert strategy.extended_lint_command == "golangci-lint run {file}"

    def test_skip_paths_is_tuple(self, strategy: GoLintStrategy) -> None:
        assert isinstance(strategy.skip_paths, tuple)


class TestToolUnavailableDetection:
    """`go vet` outside a module reports a CONTEXT failure, not a code failure.

    `go vet` resolves packages, so it needs a module. In a repository with no
    `go.mod` — any polyglot repo that merely contains a `.go` file — it exits
    non-zero with "cannot find main module" before reading the file at all.
    Treating that as a lint finding DENIES valid Go: `go vet <file>` on the
    very same file exits 0.

    Same shape as the rustup clippy-driver shim (see `rust_strategy`): the
    launcher ran, so no FileNotFoundError fires, but its non-zero says nothing
    about the file's content. Both must degrade to an advisory ALLOW.
    """

    def test_recognises_missing_module_message(self, strategy: GoLintStrategy) -> None:
        output = (
            "go: cannot find main module, but found .git/config in /workspace\n"
            "\tto create a module there, run:\n\tgo mod init\n"
        )
        assert strategy.is_tool_unavailable_output(output) is True

    def test_recognises_go_mod_absence_phrasing(self, strategy: GoLintStrategy) -> None:
        assert (
            strategy.is_tool_unavailable_output("go.mod file not found in current directory")
            is True
        )

    def test_a_genuine_vet_finding_is_not_classified_as_unavailable(
        self, strategy: GoLintStrategy
    ) -> None:
        output = (
            "# example.com/m\n"
            "./main.go:5:2: fmt.Printf format %d has arg s of wrong type string\n"
        )
        assert strategy.is_tool_unavailable_output(output) is False

    def test_a_syntax_error_is_not_classified_as_unavailable(
        self, strategy: GoLintStrategy
    ) -> None:
        assert (
            strategy.is_tool_unavailable_output("./x.go:3:1: syntax error: unexpected EOF") is False
        )

    def test_empty_output_is_not_classified_as_unavailable(self, strategy: GoLintStrategy) -> None:
        assert strategy.is_tool_unavailable_output("") is False


class TestAcceptanceTests:
    def test_returns_list(self, strategy: GoLintStrategy) -> None:
        tests = strategy.get_acceptance_tests()
        assert isinstance(tests, list)

    def test_returns_at_least_one_test(self, strategy: GoLintStrategy) -> None:
        tests = strategy.get_acceptance_tests()
        assert len(tests) >= 1
