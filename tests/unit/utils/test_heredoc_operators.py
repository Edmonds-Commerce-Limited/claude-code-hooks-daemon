"""One heredoc delimiter parser, following bash's grammar (Plan 00466 N120).

Three sites each carried their own ``<<`` regex, with three different
delimiter charsets (``\\w+``, ``[\\w.\\-]+``, ``[A-Za-z_]\\w*``) and none
accepting ``<<\\EOF``. An unrecognised heredoc is not a near miss: its body is
read as shell, and a prose apostrophe there made the write-target tokeniser
give up on the whole command.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.utils.heredoc_operators import (
    HeredocOperator,
    find_heredoc_operators,
    remove_line_continuations,
    scan_heredocs,
    substitution_end,
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
    ("x=`cat <<X`", "X"),
    ("echo a\\\r\n#<<X", "X"),
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


#: Scripts whose ``echo M<n>`` lines bash may or may not run. Plan 00466 N101
#: round 10 (review 9 MAJOR B, BLOCKER A): continuations, contexts and
#: backticks, each read by bash 5.2 in the test itself.
_LINE_DIFFERENTIAL_SCRIPTS: list[str] = [
    "cat <<EOF\necho M1\\\nEOF\necho M2\nEOF\necho M3",
    "cat <<'EOF'\necho M1\\\nEOF\necho M2\nEOF\necho M3",
    "cat <<\\EOF\necho M1\\\nEOF\necho M2",
    "cat <<'E F'\necho M1\\\nE F\necho M2",
    "cat <<EOF\necho M1\\\\\nEOF\necho M2",
    "cat <<EOF\necho M1\n\\\nEOF\necho M2",
    "cat <<EO\\\nF\necho M1\nEOF\necho M2",
    "cat <<\\\nEOF\necho M1\nEOF\necho M2",
    "cat <<\\\n-EOF\n\techo M1\n\tEOF\necho M2",
    "cat <<'EOF'\necho M1\nEO\\\nF\necho M2\nEOF\necho M3",
    "echo a\\\n# <<X\necho M1\nX\necho M2",
    "echo a \\\n# <<X\necho M1\nX\necho M2",
    "echo 'a\\\n' <<X\necho M1\nX\necho M2",
    "# note \\\necho M1",
    "x=`cat <<X`\necho M1\nX\necho M2",
    "echo `echo 'a`; cat <<X\necho M1\nX\n'`\necho M2",
    ": `cat <<X\necho M1\nX\n`\necho M2",
    "cat <<'A' <<B\necho M1\nA\necho M2\nB\necho M3",
    ": $(cat <<X\necho M1\nX\n)\necho M2",
    ": \"$(cat <<'X'\necho M1\nX\n)\"\necho M2",
    "echo $((1<<2))\ncat <<X\necho M1\nX\necho M2",
    "echo $((echo x) ) <<X\necho M1\nX\necho M2",
    "((cat <<X\necho M1\nX\n) )\necho M2",
    "a=(x\ny) <<X\necho M1\nX\necho M2",
    "cat <<X ${y:-a\nb}\necho M1\nX\necho M2",
    "cat <<a${x}b\necho M1\na${x}b\necho M2",
    "echo $\\\n(echo) <<X\necho M1\nX\necho M2",
    "echo a\\\r\n#<<X\necho M1\nX",
    "cat <(cat <<X\necho M1\nX\n)\necho M2",
]

_MARK_LINE = re.compile(r"echo (M\d)")


def _bash_stdout(script: str, tmp_path: Path) -> list[str]:
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
    return result.stdout.splitlines()


class TestEveryLineIsReadAsBashReadsIt:
    """A marker line bash runs is never inside a reported body; where the
    scan did not stop, a marker bash does not run is inside one too."""

    @pytest.mark.parametrize("script", _LINE_DIFFERENTIAL_SCRIPTS)
    def test_the_scan_agrees_with_bash(self, script: str, tmp_path: Path) -> None:
        ran = set(_bash_stdout(script, tmp_path))
        scan = scan_heredocs(script)
        spans = [(h.body_start, h.closer_end) for h in scan.heredocs]
        for match in _MARK_LINE.finditer(script):
            in_body = any(start <= match.start() < end for start, end in spans)
            if match.group(1) in ran:
                assert not in_body, match.group(1)
            elif scan.stopped_at is None:
                assert in_body, match.group(1)


class TestTheScanStopsWhereBashIsUncertain:
    """The coordinator's round-10 ruling: past a point the scanner cannot be
    sure how bash splits operators from bodies, it reads no body, and every
    newline is a command break."""

    @pytest.mark.parametrize(
        ("script", "stop"),
        [
            ("echo $((echo x) ) <<X\nbody\nX", "$((echo"),
            ("((cat <<X\nbody\nX\n) )", "((cat"),
            ("cat <<a${x}b\nbody\na${x}b", "<<a${x}b"),
            ("cat <<X ${y:-a\nb}\nbody\nX", "\nb}"),
            ("echo a\\\n# <<X\nbody\nX", "\\\n#"),
            ("echo $\\\n(date) <<X\nbody\nX", "\\\n(date"),
            ("echo `echo 'a`; cat <<X\nbody\nX\n'`", "`echo 'a"),
            ("echo 'open\n<<X\nbody\nX", "'open"),
        ],
    )
    def test_no_body_is_reported_past_the_stop(self, script: str, stop: str) -> None:
        scan = scan_heredocs(script)
        stopped_at = script.index(stop)
        assert scan.stopped_at == stopped_at
        assert scan.heredocs == []
        newlines = [i for i, char in enumerate(script) if char == "\n" and i >= stopped_at]
        assert set(newlines) <= set(scan.breaks)

    def test_a_heredoc_closed_before_the_stop_is_kept(self) -> None:
        script = "cat <<'A'\nbody\nA\necho $((echo x) )"
        scan = scan_heredocs(script)
        assert scan.stopped_at == script.index("$((")
        assert _bodies(script) == [("A", "body", True)]

    def test_an_operator_opened_in_backticks_has_no_body_after_them(self) -> None:
        """Bash 5.2 gives it an empty body inside the substitution and runs
        the next lines, so they are commands and nothing is uncertain."""
        script = "x=`cat <<X`\nbody\nX"
        scan = scan_heredocs(script)
        assert (scan.heredocs, scan.stopped_at) == ([], None)
        assert scan.breaks == [script.index("\n"), script.rindex("\n")]

    def test_the_operators_on_a_fragment_are_all_reported(self) -> None:
        """``find_heredoc_operators`` reads one opener line, which a
        substitution often leaves open."""
        assert _delimiters("x=`cat <<X`") == [("X", False, False)]


class TestNormalisingKeepsTheStructure:
    """MAJOR B: the continuations removed are the scan's, so the normalised
    text scans to the same heredocs, and stops where the raw text did."""

    @pytest.mark.parametrize(
        "script",
        [
            *_LINE_DIFFERENTIAL_SCRIPTS,
            *(f"{opener}\n{_MARK}\n{closer}" for opener, closer in _NON_OPERATOR_OPENERS),
        ],
    )
    def test_a_rescan_of_the_normalised_text_matches(self, script: str) -> None:
        raw = scan_heredocs(script)
        normalised = scan_heredocs(remove_line_continuations(script))
        shape = [(h.operator.delimiter, h.operator.quoted, h.terminated) for h in raw.heredocs]
        assert [
            (h.operator.delimiter, h.operator.quoted, h.terminated) for h in normalised.heredocs
        ] == shape
        assert (normalised.stopped_at is None) == (raw.stopped_at is None)

    @pytest.mark.parametrize(
        ("script", "expected"),
        [
            ("git pu\\\nsh --force", "git push --force"),
            ("echo a\\\\\nb", "echo a\\\\\nb"),
            ("# c \\\ngit reset", "# c \\\ngit reset"),
            ("cat <<'EOF'\nfoo\\\nEOF", "cat <<'EOF'\nfoo\\\nEOF"),
            ("bash <<'EOF'\ngit reset --ha\\\nrd\nEOF", "bash <<'EOF'\ngit reset --hard\nEOF"),
            ("cat <<EOF\nfoo\\\nbar\nEOF", "cat <<EOF\nfoobar\nEOF"),
            ("bash -c 'git pu\\\nsh'", "bash -c 'git push'"),
            ("echo a\\\n# <<X", "echo a\\\n# <<X"),
        ],
    )
    def test_what_is_joined_and_what_is_kept(self, script: str, expected: str) -> None:
        assert remove_line_continuations(script) == expected


class TestSubstitutionEnd:
    """Check 2: the brace-word reader asks the shared scanner where a
    substitution holding a heredoc ends."""

    def test_a_heredoc_body_holding_a_paren(self) -> None:
        text = 'x "$(cat <<E\n)\nE\n)" y'
        assert substitution_end(text, text.index("(")) == text.index('" y')

    def test_an_uncertain_substitution_has_no_end(self) -> None:
        text = "x $(cat ${y:-<<E\n)\nE\n) y"
        assert substitution_end(text, text.index("(")) is None
