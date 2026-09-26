"""Tests for ``shell_expansion.brace_expansion_view`` (Plan 00466 N101).

Bash brace-expands only UNQUOTED shell words. A Python program handed to
``python3`` as a quoted-delimiter heredoc or a single-quoted ``-c`` argument
reaches Python verbatim, so enumerating its dict literals and f-strings as
brace "spellings" models nothing bash does -- and trips the bounded
expander's cap, failing the secret guard closed on an ordinary command.

The view neutralises exactly that program text, and only when nothing on
the command line can turn it back into shell text: Python only (Ruby, Perl,
PHP and Node brace-expand in their own glob APIs), the program text only
(never argv), and only for a standalone simple command no shell reads the
output of. Everything else, and everything the scanner is not sure about, is
returned unchanged, so the caller keeps enumerating it and keeps failing
closed past the cap.
"""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.utils.shell_expansion import (
    brace_expansion_view,
    python_string_literals,
)

_GROUPS = "{a,b}{c,d}"


def _python_heredoc(body: str, *, opener_tail: str = "", quote: str = "'") -> str:
    return f"python3 - <<{quote}EOF{quote}{opener_tail}\n{body}\nEOF"


def _kept(command: str) -> bool:
    return brace_expansion_view(command).text == command


class TestLengthAndIdentity:
    def test_view_is_the_same_length_as_the_command(self) -> None:
        command = _python_heredoc(f"print('{_GROUPS}')")
        assert len(brace_expansion_view(command).text) == len(command)

    def test_a_command_with_no_quoted_text_is_unchanged(self) -> None:
        assert _kept(f"echo {_GROUPS} && ls *.py")


class TestPythonProgramTextIsNeutralised:
    @pytest.mark.parametrize(
        "command",
        [
            _python_heredoc(f"print('{_GROUPS}')"),
            f"python3 <<'EOF'\nprint('{_GROUPS}')\nEOF",
            f"python3 -u - <<'EOF'\nprint('{_GROUPS}')\nEOF",
            f"python3.12 - <<\"EOF\"\nprint('{_GROUPS}')\nEOF",
            f"/usr/bin/python3 - <<'EOF'\nprint('{_GROUPS}')\nEOF",
            f"PYTHONDONTWRITEBYTECODE=1 python3 - <<'EOF'\nprint('{_GROUPS}')\nEOF",
            f"python3 -c 'print(\"{_GROUPS}\")'",
            f"python3 -B -W ignore -c 'print(\"{_GROUPS}\")'",
            f"python3 -c 'print(\"{_GROUPS}\")' 2>&1",
            f"python3 -c 'print(\"{_GROUPS}\")' >/dev/null 2>&1",
            f"cd /x && python3 - <<'EOF'\nprint('{_GROUPS}')\nEOF\necho done",
            f"set -e; python3 - <<'EOF' > out.json\nprint('{_GROUPS}')\nEOF",
            f"python3 - <<'EOF' &\nprint('{_GROUPS}')\nEOF",
        ],
    )
    def test_program_braces_are_neutralised(self, command: str) -> None:
        assert "{a,b}" not in brace_expansion_view(command).text

    def test_the_opener_line_keeps_its_shell_braces(self) -> None:
        command = _python_heredoc(f"x = '{_GROUPS}'", opener_tail=f" x{_GROUPS}")
        assert f"x{_GROUPS}" in brace_expansion_view(command).text.split("\n")[0]

    def test_text_after_the_closer_is_still_shell(self) -> None:
        command = _python_heredoc(f"x = '{_GROUPS}'") + f"\ncat x{_GROUPS}"
        assert brace_expansion_view(command).text.endswith(f"cat x{_GROUPS}")


class TestOnlyPython:
    """D-SEC F1: Ruby's Dir.glob, Perl's glob, PHP's GLOB_BRACE and Node's
    fs.glob expand braces in-process, so their text is judged as before."""

    @pytest.mark.parametrize(
        "command",
        [
            f"ruby - <<'EOF'\nDir.glob('x{_GROUPS}')\nEOF",
            f"perl - <<'EOF'\nglob('x{_GROUPS}')\nEOF",
            f"php <<'EOF'\n<?php glob('x{_GROUPS}', GLOB_BRACE);\nEOF",
            f"node - <<'EOF'\nfs.globSync('x{_GROUPS}')\nEOF",
            f"pypy3 - <<'EOF'\nprint('{_GROUPS}')\nEOF",
            f"ruby -e 'Dir.glob(\"x{_GROUPS}\")'",
            f"perl -e 'glob(\"x{_GROUPS}\")'",
            f"php -r 'glob(\"x{_GROUPS}\", GLOB_BRACE);'",
            f"node -e 'fs.globSync(\"x{_GROUPS}\")'",
        ],
    )
    def test_other_interpreters_keep_their_text(self, command: str) -> None:
        assert _kept(command)


class TestOnlyTheProgramText:
    """D-RULE F3 / D-SEC minor 3: argv is data an arbitrary program consumes."""

    @pytest.mark.parametrize(
        "command",
        [
            f"python3 script.py 'cat x{_GROUPS}'",
            f"python3 -m mod 'cat x{_GROUPS}'",
            f"python3 -c 'import sys' 'cat x{_GROUPS}'",
            f"python3 script.py <<'EOF'\ncat x{_GROUPS}\nEOF",
            f"python3 -c \"print('{_GROUPS}')\"",
            f"python3 -c $'print(\"{_GROUPS}\")'",
            f"python3 --isolated -c 'print(\"{_GROUPS}\")'",
            f"python3 -Bc 'print(\"{_GROUPS}\")'",
            f"python3 -c 'print(\"{_GROUPS}\")'x",
            f"python3 - <<-'EOF'\n\tprint('{_GROUPS}')\n\tEOF",
            f"python3 - < prog.py <<'EOF'\nprint('{_GROUPS}')\nEOF",
            f"python3 - <<<'x' <<'EOF'\nprint('{_GROUPS}')\nEOF",
            f"python3 - <<'A' <<'B'\nprint('{_GROUPS}')\nA\nprint('{_GROUPS}')\nB",
            _python_heredoc(f"print('{_GROUPS}')", quote=""),
        ],
    )
    def test_anything_but_the_program_is_kept(self, command: str) -> None:
        assert _kept(command)

    def test_a_c_program_leaves_its_argv_enumerated(self) -> None:
        view = brace_expansion_view(f"python3 -c 'print(\"{_GROUPS}\")' 'cat y{_GROUPS}'")
        assert f"'cat y{_GROUPS}'" in view.text
        assert f'"{_GROUPS}"' not in view.text


class TestNoShellMayReadTheOutput:
    """D-RULE F1 and F2: every route from the program's output to a shell."""

    @pytest.mark.parametrize(
        "command",
        [
            # F1: a -c program
            f"python3 -c 'print(\"cat x{_GROUPS}\")' | bash",
            f"python3 -c 'print(\"cat x{_GROUPS}\")' |& bash",
            f"python3 -c 'print(\"cat x{_GROUPS}\")' | xargs sh -c",
            f"python3 -c 'print(\"cat x{_GROUPS}\")' > >(bash)",
            f'python3 -c \'print("cat x{_GROUPS}")\' | while read l; do bash -c "$l"; done',
            f"python3 -c 'print(\"cat x{_GROUPS}\")' 2>&1 | grep -v noise",
            # F2: a heredoc program
            f"( python3 - <<'EOF'\nprint('cat x{_GROUPS}')\nEOF\n) | bash",
            f"{{ python3 - <<'EOF'\nprint('cat x{_GROUPS}')\nEOF\n}} | bash",
            f"python3 - <<'EOF' > >(bash)\nprint('cat x{_GROUPS}')\nEOF",
            f"python3 - <<'EOF' | tee >(bash)\nprint('cat x{_GROUPS}')\nEOF",
            f"python3 - <<'EOF' > gen.sh\nprint('cat x{_GROUPS}')\nEOF\nbash gen.sh",
            f"python3 - <<'EOF' >> gen.sh\nprint('cat x{_GROUPS}')\nEOF\n. ./gen.sh",
            f"python3 - x>gen.sh <<'EOF'\nprint('cat x{_GROUPS}')\nEOF\nbash gen.sh",
            f"python3 - <<'EOF' 3>gen.sh >&3\nprint('cat x{_GROUPS}')\nEOF\nbash gen.sh",
            _python_heredoc(f"print('cat x{_GROUPS}')", opener_tail=" | bash"),
            _python_heredoc(f"print('x{_GROUPS}')", opener_tail=" 2>&1 | grep -v noise"),
            # Compound commands and re-routing of the shell's own stdout
            f"for i in 1; do python3 -c 'print(\"cat x{_GROUPS}\")'; done | bash",
            f"if true; then python3 -c 'print(\"cat x{_GROUPS}\")'; fi > gen.sh",
            f"while true; do python3 - <<'EOF'\nprint('x{_GROUPS}')\nEOF\ndone | bash",
            f"exec > gen.sh; python3 -c 'print(\"cat x{_GROUPS}\")'; bash gen.sh",
            f"eval 'exec >gen.sh'; python3 -c 'print(\"cat x{_GROUPS}\")'",
            f"coproc bash; python3 -c 'print(\"cat x{_GROUPS}\")' >&${{COPROC[1]}}",
            # Substitutions, wrappers and remote hosts
            f"bash -c \"$(python3 - <<'EOF'\nprint('cat x{_GROUPS}')\nEOF\n)\"",
            f'bash -c "$(python3 -c \'print(\\"cat x{_GROUPS}\\")\')"',
            f"bash -c `python3 -c 'print(\"cat x{_GROUPS}\")'`",
            f"cat <(python3 -c 'print(\"x{_GROUPS}\")')",
            f"xargs python3 -c 'print(\"cat x{_GROUPS}\")'",
            f"ssh host python3 -c 'print(\"cat x{_GROUPS}\")'",
            f"sudo python3 -c 'print(\"cat x{_GROUPS}\")'",
            f"env python3 -c 'print(\"cat x{_GROUPS}\")'",
            f"timeout 5 python3 -c 'print(\"cat x{_GROUPS}\")'",
        ],
    )
    def test_a_program_whose_output_a_shell_may_read_is_kept(self, command: str) -> None:
        assert _kept(command)


class TestTheInterpreterMustBePython:
    """D-SEC F2 and D-RULE F5: the command word, not a flag's value, and no
    name redefined in the same command."""

    @pytest.mark.parametrize(
        "command",
        [
            f"sudo -p python3 bash -c 'cat x{_GROUPS}'",
            f"sudo -p python3 bash <<'EOF'\ncat x{_GROUPS}\nEOF",
            f"sudo -u python3 bash -c 'cat x{_GROUPS}'",
            f"./python3 -c 'cat x{_GROUPS}'",
            f"bin/python3 -c 'cat x{_GROUPS}'",
            f"/tmp/shim/python3 -c 'cat x{_GROUPS}'",
            f"\\python3 -c 'cat x{_GROUPS}'",
            f"'python3' -c 'cat x{_GROUPS}'",
            f"python3() {{ bash -c \"$1\"; }}; python3 -c 'cat x{_GROUPS}'",
            f"function python3 {{ bash; }}; python3 -c 'cat x{_GROUPS}'",
            f"alias python3=bash; python3 -c 'cat x{_GROUPS}'",
            f"PATH=/tmp/shim:$PATH; python3 -c 'cat x{_GROUPS}'",
            f"export PATH=/tmp/shim:$PATH && python3 -c 'cat x{_GROUPS}'",
            f"read PATH < f; python3 -c 'cat x{_GROUPS}'",
            f"hash -p /bin/bash python3; python3 -c 'cat x{_GROUPS}'",
            f". ./defs.sh; python3 -c 'cat x{_GROUPS}'",
            f"source defs.sh; python3 -c 'cat x{_GROUPS}'",
            f"source defs.sh && python3 - <<'EOF'\nprint('x{_GROUPS}')\nEOF",
            f"ln -s /bin/bash ./python3 && ./python3 - <<'EOF'\ncat x{_GROUPS}\nEOF",
            # Round 3: interpreter startup settings that load other code
            "PYTHONPATH=src python3 -c 'print(1, {1})'",
            "export PYTHONPATH=src; python3 -c 'print(1, {1})'",
            "PYTHONHOME=/x python3 -c 'print(1, {1})'",
            "PYTHONUSERBASE=/x python3 -c 'print(1, {1})'",
        ],
    )
    def test_an_untrusted_interpreter_name_keeps_its_text(self, command: str) -> None:
        assert _kept(command)

    def test_redefinition_words_inside_the_program_are_not_redefinitions(self) -> None:
        command = f"python3 - <<'EOF'\nalias = hash = 1\nmain()\nPATH = '{_GROUPS}'\nEOF"
        assert "{a,b}" not in brace_expansion_view(command).text

    def test_a_dot_argument_is_not_a_source_command(self) -> None:
        command = f"grep -rn x . ; python3 -c 'print(\"{_GROUPS}\")'"
        assert "{a,b}" not in brace_expansion_view(command).text


#: A program the view exempts on its own: code braces only.
_PROGRAM = f"python3 -c 'print({{1}}, \"{_GROUPS}\")'"


def _spellings(name: str) -> list[str]:
    """``name`` quoted, backslashed and partly quoted: every spelling bash
    resolves to the same word after quote removal."""
    spellings = [f"'{name}'", f'"{name}"', f"\\{name}"]
    if len(name) > 1:
        spellings += [
            f"{name[0]}\\{name[1:]}",
            f"{name[0]}'{name[1:]}'",
            f'{name[:-1]}"{name[-1]}"',
        ]
    return spellings


class TestWithdrawingWordsAreJudgedAfterQuoteRemoval:
    """Plan 00466 N101 round 3 (D-RULE B1 and M1, D-SEC minor 3): bash
    removes quotes and backslashes before it looks a name up, so `'exec'`,
    `\\exec` and `e\\xec` are all `exec`. Every head and redefinition word is
    compared after quote removal, and a word that cannot be resolved with
    certainty withdraws the exemption."""

    @pytest.mark.parametrize(
        "head",
        [
            spelling
            for name in ("exec", "eval", "source", ".", "coproc", "builtin", "command")
            for spelling in _spellings(name)
        ],
    )
    def test_a_quoted_or_escaped_withdrawing_head_withdraws(self, head: str) -> None:
        assert _kept(f"{head} x >gen.sh; {_PROGRAM}; bash gen.sh")

    @pytest.mark.parametrize(
        "prefix",
        [
            ">gen.sh exec",
            "X=1 exec >gen.sh",
            "2>/dev/null 'exec' >gen.sh",
            "$e >gen.sh",
            "${e} >gen.sh",
            "$(echo exec) >gen.sh",
            "`echo exec` >gen.sh",
            "ex?c >gen.sh",
            "{exec,} >gen.sh",
            "$'exec' >gen.sh",
        ],
    )
    def test_a_head_behind_a_prefix_or_built_by_expansion_withdraws(self, prefix: str) -> None:
        assert _kept(f"{prefix}; {_PROGRAM}; bash gen.sh")

    @pytest.mark.parametrize(
        "redefinition",
        [
            *(f"{spelling} -p /bin/true python3" for spelling in _spellings("hash")),
            *(f"{spelling} python3=bash" for spelling in _spellings("alias")),
            *(f"{spelling} -f ./x.so python3" for spelling in _spellings("enable")),
            'export "PATH=/opt/x"',
            "export P\\ATH=/opt/x",
            "export 'PATH'=/opt/x",
            "declare -x P'A'TH=/opt/x",
            'printf -v "PA"TH /opt/x',
            "read -r P\\ATH < f",
            "export $v",
            'declare "$v"',
            "read -r $v < f",
            "export PYTHON\\PATH=src",
            "export 'PYTHONSTARTUP'=x",
        ],
    )
    def test_a_quoted_or_escaped_redefinition_withdraws(self, redefinition: str) -> None:
        assert _kept(f"{redefinition}; {_PROGRAM}")

    @pytest.mark.parametrize(
        "sibling",
        [
            "cd /x",
            "cd '/x y'",
            'echo "done"',
            "echo $HOME",
            "PYTHONDONTWRITEBYTECODE=1 true",
        ],
    )
    def test_an_ordinary_sibling_keeps_the_exemption(self, sibling: str) -> None:
        assert "{a,b}" not in brace_expansion_view(f"{sibling}; {_PROGRAM}").text


class TestUncertainInputIsReturnedUnchanged:
    @pytest.mark.parametrize(
        "command",
        [
            f"python3 -c 'unterminated {_GROUPS}",
            f"python3 - <<'EOF'\nx = '{_GROUPS}'\nno closer",
            f"case x in a) python3 -c '{_GROUPS}' ;; esac",
            f"python3 -c \"$(echo 'x' {_GROUPS}\"",
            f"python3 - <<'EOF'\nprint('{_GROUPS}'\nEOF",
        ],
    )
    def test_unparseable_command_or_program_is_unchanged(self, command: str) -> None:
        assert _kept(command)


class TestEveryLiteralOfAnExemptedProgramIsReported:
    """Plan 00466 N101 round 3 (coordinator ruling on D-SEC MAJOR 1 and 2):
    only a Python string literal (or a comment the program can read back
    from its own command line) can spell a path, so every one is reported
    and the caller enumerates each on its own -- whatever the program does
    with it. No analysis of what the program reaches is needed."""

    def test_a_printing_program_reports_its_literals(self) -> None:
        literals = brace_expansion_view(_python_heredoc(f"print('cat x{_GROUPS}')")).literals
        assert f"cat x{_GROUPS}" in literals

    @pytest.mark.parametrize(
        "body",
        [
            # D-SEC MAJOR 1: a shell call fetched by a name built at runtime
            "import os, operator\n"
            "f = operator.attrgetter('sys' + 'tem')(os)\n"
            f"f('cat x{_GROUPS}')",
            # D-SEC MAJOR 2: a script written through a renamed os.open
            "from os import open as o, pwrite, O_WRONLY, O_CREAT\n"
            f"pwrite(o('g.sh', O_WRONLY | O_CREAT), b'cat x{_GROUPS}', 0)",
            # D-RULE m2: a name computed from dir()
            "import os\n"
            "n = [a for a in dir(os) if a.endswith('ystem')][0]\n"
            f"print(n, 'cat x{_GROUPS}')",
        ],
    )
    def test_a_program_reaching_anything_reports_its_literals(self, body: str) -> None:
        view = brace_expansion_view(_python_heredoc(body))
        assert "{a,b}" not in view.text
        assert any(f"cat x{_GROUPS}" in literal for literal in view.literals)

    def test_a_comment_is_reported(self) -> None:
        literals = brace_expansion_view(_python_heredoc(f"print(1)  # cat x{_GROUPS}")).literals
        assert any(f"cat x{_GROUPS}" in literal for literal in literals)

    def test_code_braces_are_not_reported(self) -> None:
        body = "x = {'k': {1, 2}}\ny = [i for i in {3, 4}]\nprint(f'{x}{y!r:>{3}}')"
        literals = brace_expansion_view(_python_heredoc(body)).literals
        assert not any("{1, 2}" in literal or "{3, 4}" in literal for literal in literals)

    def test_a_program_that_does_not_parse_is_not_exempted(self) -> None:
        command = _python_heredoc(f"x = = '{_GROUPS}'")
        assert _kept(command)
        assert brace_expansion_view(command).literals == ()


class TestPythonStringLiterals:
    """``python_string_literals``: every literal the program's text spells,
    found by Python's own tokenizer and parser."""

    def test_every_kind_of_string_literal_is_reported(self) -> None:
        literals = python_string_literals("a = 'x{a,b}'\nc = b'w{1,2}'\nd = r'\\d{a,b}'\n")
        assert literals is not None
        assert {"x{a,b}", "w{1,2}", "\\d{a,b}"} <= set(literals)

    def test_implicit_concatenation_reports_each_part_and_the_whole(self) -> None:
        literals = python_string_literals("x = '/p{a,' 'x}ss'\n")
        assert literals is not None
        assert {"/p{a,", "x}ss", "/p{a,x}ss"} <= set(literals)

    def test_an_f_string_reports_its_literal_text_unescaped(self) -> None:
        literals = python_string_literals("d = 1\nx = f'cat {d}/.p{{a,x}}ss'\n")
        assert literals is not None
        assert "/.p{a,x}ss" in literals

    def test_a_string_inside_an_f_string_field_is_reported(self) -> None:
        literals = python_string_literals("x = f'{g(\"p{a,b}\")}'\n")
        assert literals is not None
        assert "p{a,b}" in literals

    def test_an_escape_spelled_brace_is_decoded(self) -> None:
        literals = python_string_literals("x = 'p\\x7ba,b\\x7d'\n")
        assert literals is not None
        assert "p{a,b}" in literals

    def test_a_comment_is_reported(self) -> None:
        literals = python_string_literals("x = 1  # p{a,b}\n")
        assert literals is not None
        assert "# p{a,b}" in literals

    def test_code_braces_are_not_literals(self) -> None:
        assert python_string_literals("x = {'a': 1, 'b': {2, 3}}\n") == ("a", "b")

    @pytest.mark.parametrize("source", ["print('x", "x = = 1\n", "def f(:\n", "x = '\0'\n"])
    def test_text_that_does_not_tokenise_or_parse_is_none(self, source: str) -> None:
        assert python_string_literals(source) is None


class TestHeredocsAreReported:
    def test_a_python_heredoc_is_reported_with_its_receiver_and_body(self) -> None:
        view = brace_expansion_view(_python_heredoc("import os\nprint(1)"))
        assert len(view.heredocs) == 1
        assert view.heredocs[0].receiver == "python3"
        assert view.heredocs[0].body == "import os\nprint(1)\n"
        assert view.heredocs[0].quoted is True

    def test_an_unquoted_heredoc_is_reported_as_unquoted(self) -> None:
        view = brace_expansion_view(_python_heredoc("print(1)", quote=""))
        assert view.heredocs[0].quoted is False

    def test_a_heredoc_inside_a_substitution_is_reported(self) -> None:
        view = brace_expansion_view("x=$(ruby - <<'EOF'\nputs 1\nEOF\n)")
        assert [heredoc.receiver for heredoc in view.heredocs] == ["ruby"]

    def test_no_heredocs_when_the_command_is_unparseable(self) -> None:
        view = brace_expansion_view("python3 - <<'EOF'\nprint(1)\nno closer")
        assert view.heredocs == ()


class TestQuoteTrackingDoesNotDesync:
    @pytest.mark.parametrize(
        "command",
        [
            f"cat <<EOF\nit's here\nEOF\npython3 -c 'x' ; cat z{_GROUPS} ; echo 'q'",
            f"python3 -c 'x' # it's\ncat z{_GROUPS} #'",
            f"python3 -c \"it's\" ; cat z{_GROUPS} ; python3 -c 'y'",
            f"python3 -c $'a\\'b' ; cat z{_GROUPS} ; echo 'q'",
            f"python3 x\\' ; cat z{_GROUPS} ; echo \\'",
        ],
    )
    def test_shell_text_after_tricky_quoting_is_kept(self, command: str) -> None:
        assert f"cat z{_GROUPS}" in brace_expansion_view(command).text
