"""Tests for ``shell_expansion.brace_expansion_view`` (Plan 00466 N101).

Bash brace-expands only UNQUOTED shell words. A quoted-delimiter heredoc body
and a single-quoted argument are handed to the receiving program verbatim, so
enumerating their brace "spellings" models nothing bash does -- and a Python
program full of dict literals and f-strings then trips the bounded expander's
cap and fails the secret guard closed on an ordinary command.

The view neutralises braces ONLY where no shell will ever read the text as
shell: a quoted heredoc body or a single-quoted argument whose receiver is a
non-shell interpreter. Everything else --
and everything the scanner is not sure about -- is returned unchanged, so the
caller keeps enumerating it and keeps failing closed past the cap.
"""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.utils.shell_expansion import (
    brace_expansion_view,
    non_shell_interpreter_extension,
)

_GROUPS = "{a,b}{c,d}"


def _python_heredoc(body: str, *, opener_tail: str = "", quote: str = "'") -> str:
    return f"python3 - <<{quote}EOF{quote}{opener_tail}\n{body}\nEOF"


class TestLengthAndIdentity:
    def test_view_is_the_same_length_as_the_command(self) -> None:
        command = _python_heredoc(f"print('{_GROUPS}')")
        assert len(brace_expansion_view(command).text) == len(command)

    def test_a_command_with_no_quoted_text_is_unchanged(self) -> None:
        command = f"echo {_GROUPS} && ls *.py"
        assert brace_expansion_view(command).text == command


class TestQuotedHeredocBodies:
    def test_python_heredoc_body_braces_are_neutralised(self) -> None:
        view = brace_expansion_view(_python_heredoc(f"print('{_GROUPS}')"))
        body = view.text.split("\n")[1]
        assert "{" not in body
        assert "}" not in body

    def test_the_opener_line_keeps_its_shell_braces(self) -> None:
        command = _python_heredoc(f"x = '{_GROUPS}'", opener_tail=f" > out{_GROUPS}")
        view = brace_expansion_view(command)
        assert f"out{_GROUPS}" in view.text.split("\n")[0]

    @pytest.mark.parametrize(
        "receiver",
        ["python3", "python3.12", "/usr/bin/python3", "pypy3", "node", "ruby", "perl", "php"],
    )
    def test_every_non_shell_interpreter_receiver_is_neutralised(self, receiver: str) -> None:
        command = f"{receiver} - <<'EOF'\nx = '{_GROUPS}'\nEOF"
        assert "{" not in brace_expansion_view(command).text

    def test_double_quoted_delimiter_is_quoted_too(self) -> None:
        view = brace_expansion_view(_python_heredoc(f"x = '{_GROUPS}'", quote='"'))
        assert "{" not in view.text

    @pytest.mark.parametrize("sink", ["cat > gen.sh", "tee gen.sh", "git commit -F -"])
    def test_data_sink_receiver_body_is_kept(self, sink: str) -> None:
        """A sink's body is authored or forwarded bytes: `cat > gen.sh`
        writes a file a later command can run, judged whole like a Write."""
        command = f"{sink} <<'EOF'\ncat x{_GROUPS}\nEOF"
        assert brace_expansion_view(command).text == command

    @pytest.mark.parametrize("shell", ["bash", "sh", "/bin/bash", "sudo bash", "zsh"])
    def test_shell_receiver_body_is_kept(self, shell: str) -> None:
        command = f"{shell} <<'EOF'\ncat x{_GROUPS}\nEOF"
        assert brace_expansion_view(command).text == command

    def test_unknown_receiver_body_is_kept(self) -> None:
        command = f"at now <<'EOF'\ncat x{_GROUPS}\nEOF"
        assert brace_expansion_view(command).text == command

    def test_ssh_receiver_body_is_kept(self) -> None:
        command = f"ssh localhost <<'EOF'\ncat x{_GROUPS}\nEOF"
        assert brace_expansion_view(command).text == command

    def test_unquoted_delimiter_body_is_kept(self) -> None:
        command = _python_heredoc(f"x = '{_GROUPS}'", quote="")
        assert brace_expansion_view(command).text == command

    def test_sink_body_piped_on_to_a_shell_is_kept(self) -> None:
        command = f"cat <<'EOF' | bash\ncat x{_GROUPS}\nEOF"
        assert brace_expansion_view(command).text == command

    def test_interpreter_body_piped_on_to_a_shell_is_kept(self) -> None:
        command = _python_heredoc(f"print('cat x{_GROUPS}')", opener_tail=" | bash")
        assert brace_expansion_view(command).text == command

    def test_interpreter_body_piped_on_to_an_unknown_stage_is_kept(self) -> None:
        command = _python_heredoc(f"x = '{_GROUPS}'", opener_tail=" 2>&1 | mystery-tool")
        assert brace_expansion_view(command).text == command

    def test_interpreter_body_piped_on_to_a_data_sink_is_neutralised(self) -> None:
        command = _python_heredoc(f"x = '{_GROUPS}'", opener_tail=" 2>&1 | grep -v noise")
        assert "{" not in brace_expansion_view(command).text

    def test_a_fallback_branch_after_the_pipeline_does_not_keep_the_body(self) -> None:
        command = _python_heredoc(f"x = '{_GROUPS}'", opener_tail=" || bash fallback.sh")
        assert "{" not in brace_expansion_view(command).text

    def test_heredoc_inside_a_command_substitution_is_kept(self) -> None:
        command = f"bash -c \"$(python3 - <<'EOF'\nprint('cat x{_GROUPS}')\nEOF\n)\""
        assert brace_expansion_view(command).text == command

    def test_tab_stripping_opener_finds_its_indented_closer(self) -> None:
        command = f"python3 - <<-'EOF'\n\tx = '{_GROUPS}'\n\tEOF\necho {_GROUPS}"
        view = brace_expansion_view(command)
        assert f"x = '{_GROUPS}'" not in view.text
        assert view.text.endswith(f"echo {_GROUPS}")

    def test_text_after_the_closer_is_still_shell(self) -> None:
        command = _python_heredoc(f"x = '{_GROUPS}'") + f"\ncat x{_GROUPS}"
        assert brace_expansion_view(command).text.endswith(f"cat x{_GROUPS}")

    def test_two_heredocs_on_one_line_are_judged_separately(self) -> None:
        command = f"python3 - <<'A' && bash <<'B'\nx = '{_GROUPS}'\nA\ncat y{_GROUPS}\nB"
        view = brace_expansion_view(command)
        assert "x = '" + _GROUPS not in view.text
        assert f"cat y{_GROUPS}" in view.text

    def test_quote_characters_inside_an_unquoted_body_do_not_desync(self) -> None:
        command = f"cat <<EOF\nit's here\nEOF\npython3 -c 'x' ; cat z{_GROUPS} ; echo 'q'"
        assert f"cat z{_GROUPS}" in brace_expansion_view(command).text


class TestSingleQuotedArguments:
    def test_interpreter_code_argument_is_neutralised(self) -> None:
        view = brace_expansion_view(f"python3 -c 'print(\"{_GROUPS}\")'")
        assert "{" not in view.text

    def test_sudo_prefixed_interpreter_is_neutralised(self) -> None:
        assert "{" not in brace_expansion_view(f"sudo python3 -c 'x = \"{_GROUPS}\"'").text

    @pytest.mark.parametrize("head", ["bash -c", "sh -c", "eval", "echo", "git -c", "xargs sh -c"])
    def test_any_other_owner_keeps_its_single_quoted_text(self, head: str) -> None:
        command = f"{head} 'cat x{_GROUPS}'"
        assert brace_expansion_view(command).text == command

    def test_single_quotes_inside_a_substitution_are_kept(self) -> None:
        command = f'bash -c "$(python3 -c \'print(\\"cat x{_GROUPS}\\")\')"'
        assert brace_expansion_view(command).text == command

    def test_a_comment_apostrophe_does_not_open_a_quote(self) -> None:
        command = f"python3 -c 'x' # it's\ncat x{_GROUPS} #'"
        assert f"cat x{_GROUPS}" in brace_expansion_view(command).text

    def test_an_apostrophe_inside_double_quotes_does_not_open_a_quote(self) -> None:
        command = f"python3 -c \"it's\" ; cat x{_GROUPS} ; python3 -c 'y'"
        assert f"cat x{_GROUPS}" in brace_expansion_view(command).text

    def test_an_escaped_quote_in_ansi_c_text_does_not_close_it(self) -> None:
        command = f"python3 -c $'a\\'b' ; cat x{_GROUPS} ; echo 'q'"
        assert f"cat x{_GROUPS}" in brace_expansion_view(command).text

    def test_an_escaped_apostrophe_outside_quotes_does_not_open_one(self) -> None:
        command = f"python3 x\\' ; cat x{_GROUPS} ; echo \\'"
        assert f"cat x{_GROUPS}" in brace_expansion_view(command).text


class TestTheInterpreterNameMustBeTheRealInterpreter:
    """Brace text is only inert if `python3` really is Python. A relative
    path, or a command that redefines the name first, can make it a shell
    that then brace-expands the argument it was handed."""

    @pytest.mark.parametrize(
        "command",
        [
            "./python3 -c 'cat x{a,b}{c,d}'",
            "bin/python3 -c 'cat x{a,b}{c,d}'",
            "/tmp/shim/python3 -c 'cat x{a,b}{c,d}'",
            "python3() { bash -c \"$1\"; }; python3 -c 'cat x{a,b}{c,d}'",
            "function python3 { bash; }; python3 -c 'cat x{a,b}{c,d}'",
            "alias python3=bash; python3 -c 'cat x{a,b}{c,d}'",
            "PATH=/tmp/shim:$PATH; python3 -c 'cat x{a,b}{c,d}'",
            "export PATH=/tmp/shim:$PATH && python3 -c 'cat x{a,b}{c,d}'",
            "hash -p /bin/bash python3; python3 -c 'cat x{a,b}{c,d}'",
            "ln -s /bin/bash ./python3 && ./python3 - <<'EOF'\ncat x{a,b}{c,d}\nEOF",
        ],
    )
    def test_an_untrusted_interpreter_name_keeps_its_text(self, command: str) -> None:
        assert brace_expansion_view(command).text == command

    @pytest.mark.parametrize("path", ["/usr/bin/python3", "/bin/python3", "/usr/local/bin/node"])
    def test_a_system_interpreter_path_is_trusted(self, path: str) -> None:
        assert "{" not in brace_expansion_view(f"{path} -c 'x = \"{_GROUPS}\"'").text

    def test_function_calls_and_names_inside_a_body_are_not_redefinitions(self) -> None:
        command = f"python3 - <<'EOF'\nalias = hash = 1\nmain()\nPATH = '{_GROUPS}'\nEOF"
        assert "{" not in brace_expansion_view(command).text


class TestUncertainInputIsReturnedUnchanged:
    @pytest.mark.parametrize(
        "command",
        [
            f"python3 -c 'unterminated {_GROUPS}",
            f"python3 - <<'EOF'\nx = '{_GROUPS}'\nno closer",
            f"case x in a) python3 -c '{_GROUPS}' ;; esac",
            f"python3 -c \"$(echo 'x' {_GROUPS}\"",
        ],
    )
    def test_unparseable_command_is_unchanged(self, command: str) -> None:
        assert brace_expansion_view(command).text == command


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

    def test_no_heredocs_when_the_command_is_unparseable(self) -> None:
        view = brace_expansion_view("python3 - <<'EOF'\nprint(1)\nno closer")
        assert view.heredocs == ()


class TestNonShellInterpreterExtension:
    @pytest.mark.parametrize(
        ("basename", "extension"),
        [
            ("python3", ".py"),
            ("pypy3", ".py"),
            ("python3.12", ".py"),
            ("ruby", ".rb"),
            ("perl", ".pl"),
            ("node", ".js"),
            ("php", ".php"),
        ],
    )
    def test_recognised_interpreters(self, basename: str, extension: str) -> None:
        assert non_shell_interpreter_extension(basename) == extension

    @pytest.mark.parametrize("basename", ["bash", "sh", "python-config", "nodejs-x", "cat"])
    def test_everything_else_is_not_one(self, basename: str) -> None:
        assert non_shell_interpreter_extension(basename) is None
