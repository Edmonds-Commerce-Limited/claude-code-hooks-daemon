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
            "# example.com/m\n./main.go:5:2: fmt.Printf format %d has arg s of wrong type string\n"
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


class TestBuildConstraintsExcludeEverything:
    """Real go 1.19 output for a package whose only file is `//go:build ignore`."""

    def test_is_a_recognised_advisory_marker(self, strategy: GoLintStrategy) -> None:
        output = "package example.com/i: build constraints exclude all Go files in /tmp/ign\n"
        assert strategy.is_tool_unavailable_output(output) is True


class TestPrecheckCommand:
    def test_gofmt_syntax_check_runs_before_vet(self, strategy: GoLintStrategy) -> None:
        assert strategy.precheck_lint_commands == ("gofmt -l -e {file}",)

    def test_default_is_still_go_vet(self, strategy: GoLintStrategy) -> None:
        assert strategy.default_lint_command == "go vet {file}"


class TestMidEditOutput:
    """Findings that only mean "this edit is half of a two-edit change".

    The messages are REAL `go vet` (go 1.19) output, captured from scratch
    modules; go 1.20+ words two of them "undefined:" and "imported and not used".
    """

    EDITED = "/repo/pkg/a.go"

    @pytest.mark.parametrize(
        "output",
        [
            "# example.com/m\nvet: ./pkg/a.go:3:12: undeclared name: syscall\n",
            "# example.com/m\nvet: ./pkg/a.go:3:12: undefined: syscall\n",
            '# example.com/m\nvet: ./pkg/a.go:3:8: "os" imported but not used\n',
            '# example.com/m\nvet: ./pkg/a.go:3:8: "os" imported and not used\n',
            "# example.com/m\nvet: ./pkg/a.go:3:12: x declared but not used\n",
            "# example.com/m\nvet: ./pkg/a.go:3:12: x declared and not used\n",
            "# example.com/m\n./pkg/a.go:3:12: undefined: syscall\n./pkg/a.go:9:1: undefined: foo\n",
        ],
    )
    def test_unresolved_name_class_on_the_edited_file_is_mid_edit(
        self, strategy: GoLintStrategy, output: str
    ) -> None:
        assert strategy.is_mid_edit_output(output, self.EDITED) is True

    def test_a_genuine_vet_finding_still_denies(self, strategy: GoLintStrategy) -> None:
        output = '# example.com/m\n./pkg/a.go:5:12: fmt.Printf format %d has arg "s" of wrong type string\n'
        assert strategy.is_mid_edit_output(output, self.EDITED) is False

    def test_unreachable_code_still_denies(self, strategy: GoLintStrategy) -> None:
        assert (
            strategy.is_mid_edit_output("./pkg/a.go:5:2: unreachable code\n", self.EDITED) is False
        )

    def test_a_syntax_error_in_the_edited_file_still_denies(self, strategy: GoLintStrategy) -> None:
        output = "# example.com/m\nvet: ./pkg/a.go:3:9: expected ')', found '{'\n"
        assert strategy.is_mid_edit_output(output, self.EDITED) is False

    def test_missing_return_still_denies(self, strategy: GoLintStrategy) -> None:
        assert (
            strategy.is_mid_edit_output("vet: ./pkg/a.go:6:1: missing return\n", self.EDITED)
            is False
        )

    def test_a_mid_edit_line_does_not_excuse_a_genuine_one(self, strategy: GoLintStrategy) -> None:
        output = "./pkg/a.go:3:12: undefined: syscall\n" "./pkg/a.go:5:2: unreachable code\n"
        assert strategy.is_mid_edit_output(output, self.EDITED) is False

    def test_findings_only_in_a_sibling_file_are_mid_edit(self, strategy: GoLintStrategy) -> None:
        output = '# example.com/m\n./pkg/b.go:5:12: fmt.Printf format %d has arg "s" of wrong type string\n'
        assert strategy.is_mid_edit_output(output, self.EDITED) is True

    def test_a_sibling_syntax_error_is_mid_edit(self, strategy: GoLintStrategy) -> None:
        output = "# example.com/m\nvet: ./pkg/b.go:3:9: expected ')', found '{'\n"
        assert strategy.is_mid_edit_output(output, self.EDITED) is True

    def test_same_basename_in_another_directory_is_a_sibling(
        self, strategy: GoLintStrategy
    ) -> None:
        output = "./other/a.go:5:2: unreachable code\n"
        assert strategy.is_mid_edit_output(output, self.EDITED) is True

    def test_a_bare_relative_path_is_the_edited_file(self, strategy: GoLintStrategy) -> None:
        assert strategy.is_mid_edit_output("a.go:5:2: unreachable code\n", "/repo/a.go") is False

    def test_output_with_no_located_finding_is_not_mid_edit(self, strategy: GoLintStrategy) -> None:
        assert strategy.is_mid_edit_output("some unexpected failure\n", self.EDITED) is False
        assert strategy.is_mid_edit_output("", self.EDITED) is False


class TestAcceptanceTests:
    def test_returns_list(self, strategy: GoLintStrategy) -> None:
        tests = strategy.get_acceptance_tests()
        assert isinstance(tests, list)

    def test_returns_at_least_one_test(self, strategy: GoLintStrategy) -> None:
        tests = strategy.get_acceptance_tests()
        assert len(tests) >= 1
