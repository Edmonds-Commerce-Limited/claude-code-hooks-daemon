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

from claude_code_hooks_daemon.utils.shell_expansion import brace_expansion_view

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
            f"PYTHONPATH=src python3 - <<'EOF'\nprint('{_GROUPS}')\nEOF",
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


class TestLiteralsOfAProgramThatReachesBeyondStdout:
    """A program that spawns, writes a file or loads unknown code hands its
    string literals on, so the caller still enumerates them."""

    def test_a_printing_program_reports_no_literals(self) -> None:
        assert brace_expansion_view(_python_heredoc(f"print('{_GROUPS}')")).literals == ()

    def test_a_spawning_program_reports_its_literals(self) -> None:
        body = f"import subprocess\ncmd = 'cat x{_GROUPS}'\nsubprocess.run(cmd)"
        literals = brace_expansion_view(_python_heredoc(body)).literals
        assert f"cat x{_GROUPS}" in literals

    def test_a_program_redirected_into_a_file_reports_its_literals(self) -> None:
        literals = brace_expansion_view(
            _python_heredoc(f"print('cat x{_GROUPS}')", opener_tail=" > out.txt")
        ).literals
        assert f"cat x{_GROUPS}" in literals

    def test_one_reaching_program_reports_every_programs_literals(self) -> None:
        command = (
            f"python3 -c 'print(\"a{_GROUPS}\")'\n" "python3 - <<'EOF'\nimport local_module\nEOF"
        )
        assert f"a{_GROUPS}" in brace_expansion_view(command).literals


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
