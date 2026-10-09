"""Reading a Bash command as simple commands (Plan 00499 Phase 1b).

The write_protected_paths handler judges the verb each simple command runs.
These tests pin the reading itself: verbs after wrappers and absolute paths,
the command strings a shell runs, brace spellings and unrolled ``for`` loops.
"""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.utils.shell_expansion import TooManyToEnumerateError
from claude_code_hooks_daemon.utils.simple_commands import (
    SimpleCommand,
    brace_variants,
    nested_command_strings,
    simple_commands,
    unquote,
    unroll_for_loops,
)

KNOWN = frozenset({"rm", "cat", "tee", "bash", "sh", "git", "eval"})


def _verbs(command: str) -> list[str]:
    return [cmd.verb for cmd in simple_commands(command, known_verbs=KNOWN)]


class TestUnquote:
    @pytest.mark.parametrize(
        ("word", "expected"),
        [
            ("plain", "plain"),
            ("'a b'", "a b"),
            ('"a b"', "a b"),
            (r"a\ b", "a b"),
            ('"say \\"hi\\""', 'say "hi"'),
            ("'$X'", "$X"),
            ('"$X/y"', "$X/y"),
            ("'unterminated", "unterminated"),
            ('pre"mid"post', "premidpost"),
        ],
    )
    def test_quote_removal(self, word: str, expected: str) -> None:
        assert unquote(word) == expected


class TestVerbs:
    @pytest.mark.parametrize(
        ("command", "verb"),
        [
            ("rm x", "rm"),
            ("/bin/rm x", "rm"),
            ("/usr/bin/tee x", "tee"),
            ("FOO=1 rm x", "rm"),
            ("FOO=1 BAR=2 /bin/rm x", "rm"),
            ("sudo -u root rm x", "rm"),
            ("flock /tmp/l rm x", "rm"),
            ("chronic rm x", "rm"),
            ("ionice -c3 rm x", "rm"),
            ("doas rm x", "rm"),
            ("nice -n 5 stdbuf -o0 rm x", "rm"),
            ("if true; then rm x; fi", "rm"),
            ("for f in a; do rm $f; done", "rm"),
            ("(rm x)", "rm"),
            ("echo a | tee x", "tee"),
            ("true && rm x || cat y", "cat"),
        ],
    )
    def test_the_verb_is_the_command_that_runs(self, command: str, verb: str) -> None:
        assert verb in _verbs(command)

    def test_an_unknown_wrapper_over_an_unknown_command_keeps_its_own_verb(self) -> None:
        (cmd,) = simple_commands("flock /tmp/l python3 x.py", known_verbs=KNOWN)
        assert cmd.verb == "flock"
        assert "x.py" in cmd.operands

    def test_a_plain_verb_is_not_flagged_for_a_second_look(self) -> None:
        (cmd,) = simple_commands("rm x", known_verbs=KNOWN)
        assert cmd.reread is False

    @pytest.mark.parametrize("command", ["/bin/rm x", "flock l rm x", "sudo rm x"])
    def test_a_verb_found_behind_a_path_or_wrapper_is_flagged(self, command: str) -> None:
        (cmd,) = simple_commands(command, known_verbs=KNOWN)
        assert cmd.verb == "rm"
        assert cmd.reread is True
        assert cmd.text.startswith("rm ")

    def test_operands_are_quote_removed_and_known_variables_substituted(self) -> None:
        (cmd,) = simple_commands("F=ab; rm \"$F\" 'c d'", known_verbs=KNOWN)
        assert cmd.operands == ("ab", "c d")

    def test_a_heredoc_body_fed_to_a_data_sink_is_not_a_command(self) -> None:
        verbs = _verbs("cat > n.md <<'EOF'\nrm /x/y\nEOF")
        assert "rm" not in verbs

    def test_a_heredoc_body_fed_to_a_shell_is_commands(self) -> None:
        assert "rm" in _verbs("bash <<'EOF'\nrm /x/y\nEOF")

    def test_a_message_value_is_one_word(self) -> None:
        (cmd,) = simple_commands("git commit -m 'rm x; cat y'", known_verbs=KNOWN)
        assert cmd.verb == "git"

    def test_redirect_operands_are_set_aside(self) -> None:
        (cmd,) = simple_commands("python3 s.py < in.txt 2>/dev/null >out.txt", known_verbs=KNOWN)
        assert cmd.file_operands == ("s.py",)

    def test_a_segment_of_only_assignments_runs_nothing(self) -> None:
        assert simple_commands("A=1; B=2", known_verbs=KNOWN) == []


class TestNestedCommandStrings:
    def _first(self, command: str) -> SimpleCommand:
        return simple_commands(command, known_verbs=KNOWN)[0]

    @pytest.mark.parametrize(
        ("command", "bodies"),
        [
            ("bash -c 'rm x'", ["rm x"]),
            ('sh -c "rm x; cat y"', ["rm x; cat y"]),
            ("bash -lc 'rm x'", ["rm x"]),
            ("bash -x -c 'rm x' name", ["rm x"]),
            ("/bin/bash --norc -c 'rm x'", ["rm x"]),
            ("sudo bash -c 'rm x'", ["rm x"]),
            ("chronic sh -c 'rm x'", ["rm x"]),
            ("eval 'rm x'", ["rm x"]),
            ("eval rm x", ["rm x"]),
            ("flock /tmp/l -c 'rm x'", ["rm x"]),
            ("bash script.sh", []),
            ("bash", []),
            ("cat -c x", []),
        ],
    )
    def test_the_code_a_shell_is_handed(self, command: str, bodies: list[str]) -> None:
        assert nested_command_strings(self._first(command)) == bodies


class TestBraceVariants:
    def test_a_command_without_braces_is_its_own_only_variant(self) -> None:
        assert list(brace_variants("rm a b")) == ["rm a b"]

    def test_every_spelling_appears_in_the_joined_variant(self) -> None:
        joined = next(iter(brace_variants("rm x.{a,b}")))
        assert joined.split() == ["rm", "x.a", "x.b"]

    def test_each_spelling_is_also_the_last_operand_of_its_own_variant(self) -> None:
        variants = list(brace_variants("cp /tmp/s x.{a,b}"))
        assert "cp /tmp/s x.a" in variants
        assert "cp /tmp/s x.b" in variants

    def test_nested_groups_and_sequences(self) -> None:
        joined = next(iter(brace_variants("rm x.{a,b{c,d}} y{1..3}"))).split()
        assert {"x.a", "x.bc", "x.bd", "y1", "y2", "y3"} <= set(joined)

    @pytest.mark.parametrize("command", ["echo ${HOME}", "echo {} {a}", "echo '{a,b}'"])
    def test_text_that_is_not_a_group_is_unchanged(self, command: str) -> None:
        assert list(brace_variants(command)) == [command]

    def test_too_many_spellings_raise(self) -> None:
        with pytest.raises(TooManyToEnumerateError):
            list(brace_variants("echo " + "{a,b}" * 20))

    def test_a_group_after_an_unreadable_substitution_raises(self) -> None:
        with pytest.raises(TooManyToEnumerateError):
            list(brace_variants("echo $(date) x.{a,b}"))


class TestUnrollForLoops:
    def test_the_body_is_repeated_for_each_word(self) -> None:
        text = unroll_for_loops('for f in a.txt b.txt; do rm "$f"; done')
        assert "rm a.txt" in text
        assert "rm b.txt" in text
        assert "for" not in text

    def test_a_braced_variable_and_newline_layout(self) -> None:
        text = unroll_for_loops("for f in a\ndo\n  rm ${f}\ndone")
        assert "rm a" in text

    def test_a_command_without_a_loop_is_unchanged(self) -> None:
        command = "rm a; echo for"
        assert unroll_for_loops(command) == command

    def test_a_prefix_of_the_variable_name_is_not_replaced(self) -> None:
        text = unroll_for_loops("for f in a; do rm $fx; done")
        assert "$fx" in text

    def test_an_unreadable_word_list_becomes_a_wildcard(self) -> None:
        text = unroll_for_loops('for f in $(ls); do rm "$f"; done')
        assert "rm *" in text

    def test_a_very_long_word_list_is_bounded(self) -> None:
        words = " ".join(f"w{i}" for i in range(500))
        text = unroll_for_loops(f"for f in {words}; do rm $f; done")
        assert text.count("rm ") <= 40
        assert "rm *" in text

    def test_a_heredoc_command_is_left_alone(self) -> None:
        command = "for f in a; do cat <<EOF\nx\nEOF\ndone"
        assert unroll_for_loops(command) == command

    def test_commands_after_the_loop_are_kept(self) -> None:
        text = unroll_for_loops("for f in a; do echo $f; done; rm z")
        assert text.rstrip().endswith("rm z")
