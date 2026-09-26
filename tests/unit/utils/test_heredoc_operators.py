"""One heredoc delimiter parser, following bash's grammar (Plan 00466 N120).

Three sites each carried their own ``<<`` regex, with three different
delimiter charsets (``\\w+``, ``[\\w.\\-]+``, ``[A-Za-z_]\\w*``) and none
accepting ``<<\\EOF``. An unrecognised heredoc is not a near miss: its body is
read as shell, and a prose apostrophe there made the write-target tokeniser
give up on the whole command.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.utils.heredoc_operators import (
    HeredocOperator,
    find_heredoc_operators,
    scan_heredocs,
)


def _delimiters(line: str) -> list[tuple[str, bool, bool]]:
    return [(op.delimiter, op.quoted, op.strip_tabs) for op in find_heredoc_operators(line)]


class TestDelimiterWordGrammar:
    @pytest.mark.parametrize(
        ("line", "expected"),
        [
            ("cat <<EOF", [("EOF", False, False)]),
            ("cat <<-EOF", [("EOF", False, True)]),
            ("cat << EOF", [("EOF", False, False)]),
            ("cat <<'EOF'", [("EOF", True, False)]),
            ('cat <<"EOF"', [("EOF", True, False)]),
            ("cat <<\\EOF", [("EOF", True, False)]),
            ('cat <<E"O"F', [("EOF", True, False)]),
            ("cat > o.md <<'my-notes'", [("my-notes", True, False)]),
            ("cat <<EOF-1", [("EOF-1", False, False)]),
            ("cat <<'EOF-1'", [("EOF-1", True, False)]),
            ('cat <<"EOF-1"', [("EOF-1", True, False)]),
            ("cat <<END.MD", [("END.MD", False, False)]),
            ("cat <<-'END.MD'", [("END.MD", True, True)]),
            ("cat <<'two words'", [("two words", True, False)]),
            ("cat <<$EOF", [("$EOF", False, False)]),
        ],
    )
    def test_the_delimiter_is_the_word_after_quote_removal(
        self, line: str, expected: list[tuple[str, bool, bool]]
    ) -> None:
        assert _delimiters(line) == expected

    @pytest.mark.parametrize(
        ("line", "delimiter"),
        [
            ("cat <<EOF >out.md", "EOF"),
            ("cat <<EOF>out.md", "EOF"),
            ("cat <<EOF;", "EOF"),
            ("cat <<EOF|grep x", "EOF"),
            ("cat <<EOF&", "EOF"),
            ("(cat <<EOF)", "EOF"),
            ("cat <<EOF\tx", "EOF"),
        ],
    )
    def test_the_word_ends_at_an_unquoted_metacharacter(self, line: str, delimiter: str) -> None:
        assert [op.delimiter for op in find_heredoc_operators(line)] == [delimiter]

    def test_several_operators_on_one_line_are_all_found_in_order(self) -> None:
        assert _delimiters("cat <<A - <<'B' | cat <<-C") == [
            ("A", False, False),
            ("B", True, False),
            ("C", False, True),
        ]

    def test_offsets_span_the_operator_and_its_word(self) -> None:
        line = "cat > o.md <<'EOF' | x"
        (operator,) = find_heredoc_operators(line)
        assert operator == HeredocOperator(
            start=11, end=18, delimiter="EOF", quoted=True, strip_tabs=False
        )
        assert line[operator.start : operator.end] == "<<'EOF'"


class TestWhatIsNotAHeredoc:
    @pytest.mark.parametrize(
        "line",
        [
            "cat <<<EOF",
            "cat <<<'EOF'",
            'cat <<< "EOF"',
            "cat > /opt/n.md <<<hi",
            "cat <<",
            "cat << ;",
            "cat <<'EOF",
            'cat <<"EOF',
            "echo '<<EOF'",
            'echo "<<EOF"',
            "echo x # <<EOF",
            "echo $((1<<2))",
            "echo $(( x << 3 ))",
        ],
    )
    def test_no_operator_is_reported(self, line: str) -> None:
        assert find_heredoc_operators(line) == []

    def test_a_herestring_before_a_heredoc_does_not_hide_it(self) -> None:
        assert _delimiters("cat <<<EOF; bash <<'EOF'") == [("EOF", True, False)]

    def test_a_hash_inside_a_word_is_not_a_comment(self) -> None:
        assert _delimiters("echo a#b <<EOF") == [("EOF", False, False)]


class TestSubstitutionInsideDoubleQuotes:
    def test_the_canonical_commit_message_idiom_is_a_heredoc(self) -> None:
        assert _delimiters("git commit -m \"$(cat <<'EOF'") == [("EOF", True, False)]

    def test_a_backtick_substitution_inside_double_quotes_is_a_heredoc(self) -> None:
        assert _delimiters('echo "`cat <<EOF`"') == [("EOF", False, False)]

    def test_a_substitution_that_closed_returns_to_the_quoted_string(self) -> None:
        assert find_heredoc_operators('echo "$(date) <<EOF"') == []


def _bodies(command: str) -> list[tuple[str, str, bool]]:
    return [
        (heredoc.operator.delimiter, heredoc.body(command), heredoc.terminated)
        for heredoc in scan_heredocs(command).heredocs
    ]


class TestBodiesCloseByBashsRule:
    def test_a_prose_body_with_a_hyphenated_delimiter(self) -> None:
        command = "cat > o.md <<'my-notes'\nit's done\nmy-notes\necho x > /opt/y"
        assert _bodies(command) == [("my-notes", "it's done", True)]

    def test_only_a_line_that_is_exactly_the_delimiter_closes(self) -> None:
        assert _bodies("cat <<EOF\nhi\n EOF\nEOF \nEOF") == [("EOF", "hi\n EOF\nEOF ", True)]

    def test_strip_tabs_lets_a_tab_indented_delimiter_close(self) -> None:
        assert _bodies("cat <<-EOF\n\thi\n\tEOF\necho") == [("EOF", "\thi", True)]

    def test_several_heredocs_on_one_line_read_their_bodies_in_order(self) -> None:
        assert _bodies("cat <<A - <<'B'\na\nA\nb\nB") == [("A", "a", True), ("B", "b", True)]

    def test_an_unclosed_body_runs_to_the_end(self) -> None:
        assert _bodies("cat <<EOF\nhi\nthere") == [("EOF", "hi\nthere", False)]

    def test_a_body_inside_a_double_quoted_substitution(self) -> None:
        command = "git commit -m \"$(cat <<'EOF'\nit's done\nEOF\n)\""
        scan = scan_heredocs(command)
        assert _bodies(command) == [("EOF", "it's done", True)]
        assert scan.breaks == []

    def test_a_delimiter_followed_by_the_substitution_close_ends_the_body(self) -> None:
        assert _bodies("x=\"$(cat <<'EOF'\nhello\nEOF)\"") == [("EOF", "hello", True)]


class TestDollarQuotingAndSubstitutionWords:
    """Plan 00466 N120 (round 9d). Each shape was checked against bash 5.2.

    A delimiter read differently from bash never closes, so every later line
    is taken for body and never judged; an ANSI-C string read as a plain
    single quote ends at its escaped quote and invents an operator.
    """

    @pytest.mark.parametrize(
        ("line", "expected"),
        [
            ("cat <<$'EOF'", [("EOF", True, False)]),
            ("cat <<$'E\\x4fF'", [("EOF", True, False)]),
            ("cat <<$'it\\'s'", [("it's", True, False)]),
            ('cat <<$"EOF"', [("EOF", True, False)]),
            ("cat <<$(echo)", [("$(echo)", False, False)]),
            ("cat <<a$(echo x)b", [("a$(echo x)b", False, False)]),
            ("cat <<$((1 + 2))", [("$((1 + 2))", False, False)]),
            ("cat <<a$(echo ')')b", [("a$(echo ')')b", False, False)]),
        ],
    )
    def test_the_delimiter_is_the_word_bash_reads(
        self, line: str, expected: list[tuple[str, bool, bool]]
    ) -> None:
        assert _delimiters(line) == expected

    @pytest.mark.parametrize(
        "line",
        [
            "echo $'\\' <<\\EOF '\\'",
            "echo $'\\' <<'EOF' '\\'",
            "echo $'a\\'b <<EOF'",
            "echo x$'\\'<<EOF'",
        ],
    )
    def test_an_ansi_c_string_hides_the_operator_inside_it(self, line: str) -> None:
        assert find_heredoc_operators(line) == []

    def test_a_dollar_dollar_is_the_pid_not_an_ansi_c_opener(self) -> None:
        assert _delimiters("echo $$'\\' <<\\EOF '\\'") == [("EOF", True, False)]

    def test_an_ansi_c_opener_inside_double_quotes_is_literal(self) -> None:
        assert _delimiters("echo \"$'\" <<'EOF' \"'\"") == [("EOF", True, False)]

    @pytest.mark.parametrize(
        ("opener", "closer"),
        [("$'EOF'", "EOF"), ('$"EOF"', "EOF"), ("$(echo)", "$(echo)")],
    )
    def test_the_body_closes_where_bash_closes_it(self, opener: str, closer: str) -> None:
        command = f"cat <<{opener}\nbody\n{closer}\necho hi > /opt/x"
        scan = scan_heredocs(command)
        assert _bodies(command) == [(closer, "body", True)]
        assert command[scan.breaks[-1] + 1 :] == "echo hi > /opt/x"

    def test_the_line_after_an_ansi_c_string_is_a_command(self) -> None:
        command = "cat $'\\' <<'EOF' '\\'\ngit reset --hard\nEOF"
        scan = scan_heredocs(command)
        assert scan.heredocs == []
        assert scan.breaks == [command.index("\n"), command.rindex("\n")]


class TestCommandBreaks:
    def test_a_newline_inside_a_quoted_argument_is_not_a_break(self) -> None:
        command = 'echo "a\n<<EOF"\necho x'
        scan = scan_heredocs(command)
        assert scan.heredocs == []
        assert scan.breaks == [command.rindex("\n")]

    def test_a_comment_hides_an_operator_but_not_the_next_line(self) -> None:
        command = "# note <<EOF\necho x > /opt/y"
        scan = scan_heredocs(command)
        assert scan.heredocs == []
        assert scan.breaks == [command.index("\n")]

    def test_a_herestring_reads_no_body(self) -> None:
        command = "cat > /opt/n.md <<<'EOF'\n)\"\nEOF"
        assert scan_heredocs(command).heredocs == []

    def test_the_newline_after_a_closer_is_a_break(self) -> None:
        command = "cat <<EOF\nhi\nEOF\necho x"
        (heredoc,) = scan_heredocs(command).heredocs
        breaks = scan_heredocs(command).breaks
        assert breaks == [command.index("\n"), heredoc.closer_end]
        assert command[heredoc.body_start : heredoc.closer_end] == "hi\nEOF"


_MARK = "echo MARK-RAN"

#: ``(opener, closer)``: ``<<`` sits where bash reads no heredoc operator, or
#: where the scanner cannot be sure it does. Bash 5.2 runs the line between
#: them, so the scanner must never report that line as a body.
_NON_OPERATOR_OPENERS: list[tuple[str, str]] = [
    ("cat ${x:-<<\\EOF}", "EOF}"),
    ("cat ${x:-<<'E F'}", "E F}"),
    ("cat ${x:-<<$'EOF'}", "EOF}"),
    ('cat ${x:-<<E"O"F}', "EOF}"),
    ("cat ${x:-<<'EOF'}", "EOF}"),
    ("cat ${x:-<<EOF}", "EOF}"),
    ("cat ${x:-<<\\true }", "true"),
    ("echo $(echo ${x:-<<EOF})", "EOF"),
    ("(( y = 1 <<\\true ))", "true"),
    ("(( z = 1<<$y ))", "$y"),
    ("(( z = 1<<-1 ))", "1"),
    ("echo $[1<<$y]", "$y]"),
    ("for ((i=0; i<1<<EOF; i++)); do :; done", "EOF"),
    ("echo `# <<'X-1'`", "X-1"),
    ("a=(x <<EOF)", "EOF"),
    ("shopt -s extglob\ncat @(x|<<EOF)", "EOF)"),
    ("((cat <<EOF", "EOF\n) )"),
]


def _bash_ran_mark(script: str, tmp_path: Path) -> bool:
    bash = shutil.which("bash")
    assert bash is not None
    result = subprocess.run(
        [bash, "--norc", "--noprofile", "-c", script],
        cwd=tmp_path,
        env={"LC_ALL": "C", "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
        timeout=Timeout.QA_TEST_TIMEOUT,
    )
    return "MARK-RAN" in result.stdout


class TestNoOperatorOutsideAWordPosition:
    """Plan 00466 N101 round 10 (review 9 BLOCKER A, shared S2).

    Each case runs in bash first: the line it ran must not sit in any span
    the scanner reports as a body.
    """

    @pytest.mark.parametrize(("opener", "closer"), _NON_OPERATOR_OPENERS)
    def test_no_line_bash_runs_is_reported_as_a_body(
        self, opener: str, closer: str, tmp_path: Path
    ) -> None:
        command = f"{opener}\n{_MARK}\n{closer}"
        assert _bash_ran_mark(command, tmp_path)
        mark = command.index(_MARK)
        spans = [(h.body_start, h.closer_end) for h in scan_heredocs(command).heredocs]
        assert [span for span in spans if span[0] <= mark < span[1]] == []
