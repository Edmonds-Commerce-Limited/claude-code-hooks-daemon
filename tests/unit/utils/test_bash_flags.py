"""Tests for the shared bash safety-flag detection utility (Plan 00270).

Extracted from ``verification_result_gate`` so that handler and
``bash_safe_mode`` share ONE statement split and ONE ``set``-flag scanner.
"""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.utils.bash_flags import (
    FLAG_ERREXIT,
    FLAG_NOUNSET,
    FLAG_PIPEFAIL,
    SPAN_SEPARATORS,
    STATEMENT_SEPARATORS,
    detect_safe_mode_flags,
    has_errexit,
    sequenced_statements,
    split_statements,
)


class TestSplitStatements:
    def test_semicolon_and_newline_both_separate(self) -> None:
        assert split_statements("a; b\nc") == ["a", "b", "c"]

    def test_line_continuations_are_joined_first(self) -> None:
        statements = split_statements("git \\\n  commit -m x")
        assert [" ".join(statement.split()) for statement in statements] == ["git commit -m x"]

    def test_quoted_heredoc_body_is_not_split(self) -> None:
        statements = split_statements("cat <<'EOF'\npytest; git commit\nEOF\necho done")
        assert not any("pytest" in statement for statement in statements)

    def test_empty_segments_are_dropped(self) -> None:
        assert split_statements(";;\n\n a ;") == ["a"]

    @pytest.mark.parametrize(
        "command",
        [
            "cat > notes.md <<'EOF'\nnever run x\nEOF",
            'cat > notes.md <<"EOF"\nnever run x\nEOF',
            "cat > notes.md <<EOF\nnever run x\nEOF",
            "cat > notes.md <<EOF\nvalue $(date; hostname)\nEOF",
            "cat > notes.md <<-EOF\n\tnever run x\n\tEOF",
            "cat > notes.md <<'EOF'\na; b\nc && d\nEOF",
        ],
    )
    def test_heredoc_is_one_statement(self, command: str) -> None:
        assert len(split_statements(command)) == 1

    def test_heredoc_statement_keeps_the_opener_line(self) -> None:
        statements = split_statements("cat > notes.md <<'EOF'\nbody\nEOF")
        assert statements == ["cat > notes.md <<'EOF'"]

    def test_two_heredocs_on_separate_lines_are_two_statements(self) -> None:
        command = "cat > a <<'EOF'\none\nEOF\ncat > b <<'EOF'\ntwo\nEOF"
        assert split_statements(command) == ["cat > a <<'EOF'", "cat > b <<'EOF'"]

    def test_command_after_heredoc_terminator_is_an_extra_statement(self) -> None:
        statements = split_statements("cat > a <<'EOF'\nbody\nEOF\necho x")
        assert statements == ["cat > a <<'EOF'", "echo x"]

    def test_command_after_semicolon_on_opener_line_is_an_extra_statement(self) -> None:
        statements = split_statements("cat > a <<'EOF'; echo x\nbody\nEOF")
        assert statements == ["cat > a <<'EOF'", "echo x"]

    def test_here_string_is_not_a_heredoc(self) -> None:
        assert split_statements("cat <<< word\necho x") == ["cat <<< word", "echo x"]

    def test_interpreter_heredoc_counts_as_one_outer_statement(self) -> None:
        # The OUTER shell runs one command, `bash`; the lines of the body are
        # the inner shell's statements, which the outer shell's `set -e` does
        # not govern. Counting them here would demand a prelude that cannot
        # protect them.
        assert split_statements("bash <<'EOF'\ncmd1\ncmd2\nEOF") == ["bash <<'EOF'"]

    def test_executable_mode_keeps_interpreter_body_lines_visible(self) -> None:
        statements = split_statements(
            "bash <<'EOF'\ngit push\nrm x\nEOF", heredoc_bodies_executable=True
        )
        assert "git push" in statements
        assert "rm x" in statements

    def test_executable_mode_still_blanks_data_sink_body(self) -> None:
        statements = split_statements(
            "cat > a <<'EOF'\ngit push\nEOF", heredoc_bodies_executable=True
        )
        assert not any("git push" in statement for statement in statements)

    def test_unterminated_heredoc_body_is_still_not_split(self) -> None:
        assert split_statements("cat <<'EOF'\na\nb") == ["cat <<'EOF'"]

    def test_semicolon_inside_heredoc_body_is_not_a_boundary(self) -> None:
        assert split_statements("cat <<'EOF'\na; b\nEOF\necho x") == ["cat <<'EOF'", "echo x"]

    def test_separator_constants_are_shared(self) -> None:
        assert STATEMENT_SEPARATORS == (";", "\n")
        assert SPAN_SEPARATORS == ("||", "&&", "|")


class TestDetectSafeModeFlags:
    @pytest.mark.parametrize(
        ("statement", "expected"),
        [
            ("set -e", {FLAG_ERREXIT}),
            ("set -eu", {FLAG_ERREXIT, FLAG_NOUNSET}),
            ("set -euo pipefail", {FLAG_ERREXIT, FLAG_NOUNSET, FLAG_PIPEFAIL}),
            ("set -o errexit", {FLAG_ERREXIT}),
            ("set -o pipefail", {FLAG_PIPEFAIL}),
            ("set -o nounset", {FLAG_NOUNSET}),
            ("set -u", {FLAG_NOUNSET}),
            ("set -o errexit -o pipefail", {FLAG_ERREXIT, FLAG_PIPEFAIL}),
            ("  set -e", {FLAG_ERREXIT}),
            # Bug-fixes over the old Plan 00268 single-regex detection, which
            # required errexit in the FIRST flag cluster:
            ("set -x -e", {FLAG_ERREXIT}),
            ("set -f -e", {FLAG_ERREXIT}),
            ("set -o pipefail -o errexit", {FLAG_PIPEFAIL, FLAG_ERREXIT}),
        ],
    )
    def test_recognised_spellings(self, statement: str, expected: set[str]) -> None:
        assert detect_safe_mode_flags([statement]) == frozenset(expected)

    @pytest.mark.parametrize(
        "statement",
        [
            "set",
            "set +e",
            "set -x",
            "set -o xtrace",
            "echo set -e",
            "setter -e",
            "pytest tests/",
            # `set -- -e foo` assigns positional parameters ($1=-e); the -e
            # after `--` is an operand, not errexit. Counting it would stand
            # down verification_result_gate on an ungated command.
            "set -- -e foo",
        ],
    )
    def test_non_matching_statements_detect_nothing(self, statement: str) -> None:
        assert detect_safe_mode_flags([statement]) == frozenset()

    def test_flags_accumulate_across_statements(self) -> None:
        statements = ["set -e", "set -o pipefail", "pytest tests/"]
        assert detect_safe_mode_flags(statements) == frozenset({FLAG_ERREXIT, FLAG_PIPEFAIL})

    def test_unknown_option_name_after_dash_o_is_ignored(self) -> None:
        assert detect_safe_mode_flags(["set -o posix"]) == frozenset()


class TestHasErrexit:
    def test_true_for_any_errexit_spelling(self) -> None:
        assert has_errexit(["set -euo pipefail"]) is True
        assert has_errexit(["set -o errexit"]) is True

    def test_false_without_errexit(self) -> None:
        assert has_errexit(["set -o pipefail", "pytest"]) is False


class TestSequencedStatements:
    """N339: a `;` that is compound-command SYNTAX is not a sequencing point."""

    @pytest.mark.parametrize(
        "command",
        [
            'cd X && mkdir -p d && { ./qa.bash > d/o.txt 2>&1 && echo "exit=0" || echo "exit=$?"; }',
            "cd X && for b in a b c; do git -C x/$b rev-parse HEAD || exit 1; done",
            "while read -r l; do echo $l || exit 1; done < f",
            "until test -f x; do sleep 1 || exit 1; done",
            "if test -f x; then echo y || exit 1; fi",
            "if test -f x; then echo y; else echo z; fi",
            "if a; then b; elif c; then d; else e; fi",
            "for x in a b\ndo\n  echo $x || exit 1\ndone",
            "{\n  a && b\n}",
            "case $x in a) foo;; b) bar;; esac",
            "case $x in\n  a) foo\n  ;;\n  *) bar\n  ;;\nesac",
            "( a && b )",
            "for x in a; do for y in b; do echo $x$y || exit 1; done; done",
        ],
    )
    def test_grammar_semicolons_are_one_statement(self, command: str) -> None:
        assert len(sequenced_statements(command)) == 1

    @pytest.mark.parametrize(
        "command",
        [
            "for x in y; do a; b; done",
            "{ a; b; }",
            "if c; then a; b; fi",
            "for x in y\ndo\n a\n b\ndone",
            "case $x in a) foo; bar;; esac",
            "( a; b )",
            "a; for x in y; do b || exit 1; done",
            "for x in y; do b || exit 1; done; echo after",
            "for x in y; do b || exit 1; done\necho after",
        ],
    )
    def test_real_sequencing_still_counts(self, command: str) -> None:
        assert len(sequenced_statements(command)) >= 2

    @pytest.mark.parametrize(
        "command",
        [
            "a; done",
            "a; }",
            "a; fi",
            "for x in y; do a; b",
            "if c; then a; fi; fi",
            "for x in $(ls); do a; b; done",
            "f() { a; b; }",
            "for x in y; do a; esac",
        ],
    )
    def test_unparseable_or_unbalanced_falls_back_to_the_plain_split(self, command: str) -> None:
        assert sequenced_statements(command) == split_statements(command)

    def test_keyword_words_outside_command_position_are_inert(self) -> None:
        assert len(sequenced_statements("echo for; echo done")) == 2

    def test_quoted_keywords_are_inert(self) -> None:
        assert len(sequenced_statements("echo a; 'done'")) == 2
