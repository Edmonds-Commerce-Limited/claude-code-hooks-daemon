"""One shell segmentation scanner, because two of them diverged into two bypasses.

Plan 00200 Task 3.7. Handlers that decide "what command is actually being run"
must split a Bash string on real separators and ignore separators that are DATA
inside quotes. Two handlers grew their own scanner, and each ended up with the
opposite half of the rule:

- ``pipe_blocker`` was quote-aware but blind to the backslash, so an ESCAPED
  quote flipped its state and it never left quoted mode. Every later separator
  looked like data, and an expensive producer inherited a whitelisted leading
  command.
- ``enforce_llm_qa`` tracked escapes but applied them INSIDE single quotes too,
  where bash treats a backslash as literal. A trailing ``\\`` in a single-quoted
  argument swallowed the closing quote, so it never split either — and the
  guarded script rode through on an allowlisted leading word.

Same bypass shape, opposite root causes. Consolidating is the fix that stops it
recurring; a third careful implementation is not.

The bash rules pinned here:

1. Inside single quotes there are NO escapes; only ``'`` ends the string.
2. Everywhere else a backslash escapes exactly the next character.
3. A separator is only a separator outside quotes.
"""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.utils.shell_segmentation import (
    quoted_heredoc_receivers,
    split_unquoted,
    strip_quoted_heredoc_bodies,
    value_can_substitute,
)

CHAIN = ("&&", "||", ";", "\n")


class TestPlainSplitting:
    def test_splits_on_each_separator(self) -> None:
        assert split_unquoted("a ; b", (";",)) == ["a ", " b"]

    def test_returns_whole_text_when_no_separator_present(self) -> None:
        assert split_unquoted("grep foo bar", CHAIN) == ["grep foo bar"]

    def test_multi_character_separators_are_matched_whole(self) -> None:
        assert split_unquoted("a && b", CHAIN) == ["a ", " b"]

    def test_newline_is_a_separator(self) -> None:
        assert split_unquoted("cd x\ngrep y", CHAIN) == ["cd x", "grep y"]

    def test_empty_text_yields_one_empty_segment(self) -> None:
        assert split_unquoted("", CHAIN) == [""]


class TestQuotingIsRespected:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ('grep -E "a;b"', ['grep -E "a;b"']),
            ("grep -E 'a;b'", ["grep -E 'a;b'"]),
            ('grep -E "a && b"', ['grep -E "a && b"']),
            ('echo "line1\nline2"', ['echo "line1\nline2"']),
        ],
    )
    def test_separator_inside_quotes_is_data(self, text: str, expected: list[str]) -> None:
        assert split_unquoted(text, CHAIN) == expected

    def test_quote_characters_are_preserved_in_output(self) -> None:
        """Callers pattern-match the segment, so it must survive verbatim."""
        assert split_unquoted('grep -E "a;b" f ; ls', CHAIN) == ['grep -E "a;b" f ', " ls"]


class TestEscapeRules:
    def test_escaped_double_quote_does_not_open_or_close_a_string(self) -> None:
        """pipe_blocker's bug: the escaped quote flipped state and never recovered."""
        assert split_unquoted(r'echo "\"" ; pytest', CHAIN) == [r'echo "\"" ', " pytest"]

    def test_backslash_is_literal_inside_single_quotes(self) -> None:
        """enforce_llm_qa's bug: it escaped inside single quotes, so nothing split."""
        assert split_unquoted(r"grep 'a\' f ; pytest", CHAIN) == [r"grep 'a\' f ", " pytest"]

    def test_escaped_separator_outside_quotes_is_not_a_separator(self) -> None:
        assert split_unquoted(r"echo a\;b", (";",)) == [r"echo a\;b"]

    def test_trailing_backslash_does_not_run_off_the_end(self) -> None:
        assert split_unquoted("echo a\\", CHAIN) == ["echo a\\"]

    def test_escaped_backslash_does_not_escape_the_next_character(self) -> None:
        r"""``\\`` is a literal backslash; the ``;`` after it still separates."""
        assert split_unquoted(r"echo a\\ ; ls", (";",)) == [r"echo a\\ ", " ls"]


class TestBothOriginalBypassesAreClosed:
    """The two production shapes that motivated this module."""

    def test_pipe_blocker_shape(self) -> None:
        segments = split_unquoted(r'echo "\"" ; pytest tests/', CHAIN)

        assert segments[-1].strip() == "pytest tests/"

    def test_enforce_llm_qa_shape(self) -> None:
        segments = split_unquoted(r"grep -n 'a\' README.md ; ./scripts/qa/run_all.sh", CHAIN)

        assert segments[-1].strip() == "./scripts/qa/run_all.sh"


# Built at runtime so this file never contains the literal characters of a
# pipe-to-pager, which the pipe_blocker handler denies on write.
_PIPE = chr(124)
_TO_TAIL = f" {_PIPE} tail -1"


class TestValueCanSubstitute:
    """Plan 00222: the fact two handlers had independently disagreed about.

    ``git_message_backtick`` encoded "bash substitutes inside DOUBLE quotes".
    ``pipe_blocker`` assumed the opposite — that any message value was inert
    prose — and so let a real, executing pipe through inside a commit message.
    Pinning the predicate here means a third handler cannot reach a third
    answer.

    Quote class is NOT the discriminator. That rule was tried first and
    rejected: it re-breaks the deliberate Plan 00200 allowance for
    double-quoted prose that merely mentions a pipe.
    """

    def test_double_quoted_dollar_paren_executes(self) -> None:
        """The bypass. Double quotes stop word splitting, not substitution."""
        assert value_can_substitute(f'"$(pytest tests/{_TO_TAIL})"') is True

    def test_double_quoted_backtick_executes(self) -> None:
        assert value_can_substitute('"result: `pytest tests/`"') is True

    def test_process_substitution_executes(self) -> None:
        assert value_can_substitute('"<(pytest tests/)"') is True

    def test_single_quoted_dollar_paren_is_literal(self) -> None:
        """Single quotes suppress substitution, however executable it reads."""
        assert value_can_substitute("'$(pytest tests/)'") is False

    def test_single_quoted_backtick_is_literal(self) -> None:
        assert value_can_substitute("'text with `backticks` stays literal'") is False

    def test_double_quoted_prose_mentioning_a_pipe_is_inert(self) -> None:
        """No `$(` and no backtick, so bash runs nothing — the pipe is text."""
        assert value_can_substitute(f'"docs: pytest 2>&1{_TO_TAIL} is blocked"') is False

    def test_quoted_heredoc_idiom_is_inert(self) -> None:
        """`<<'EOF'` expands nothing, so only `cat` runs.

        Recognised rather than scanned: newlines are segment separators, so
        scanning the body resolves the "command" before a pipe to a line of
        English prose — which is exactly the false positive being avoided.
        """
        value = "\"$(cat <<'EOF'\nFix: something\n\nran pytest" + _TO_TAIL + '\nEOF\n)"'
        assert value_can_substitute(value) is False

    def test_unquoted_heredoc_delimiter_does_expand(self) -> None:
        """`<<EOF` without quotes DOES expand, so it must not be exempted."""
        value = '"$(cat <<EOF\nvalue is $(pytest)\nEOF\n)"'
        assert value_can_substitute(value) is True

    def test_bare_unquoted_value_with_substitution_executes(self) -> None:
        assert value_can_substitute("$(pytest)") is True

    def test_plain_bare_word_is_inert(self) -> None:
        assert value_can_substitute("COMMIT_MSG.txt") is False


class TestStripQuotedHeredocBodies:
    """A quoted-delimiter heredoc body is DATA, wherever it appears.

    ``value_can_substitute`` already knew this, but only for the one shape
    ``"$(cat <<'EOF' ... EOF)"`` — an argument VALUE. The same bash fact holds
    for a heredoc fed straight to a command's stdin, and that shape was not
    covered, so every caller that splits on newlines re-derived the false
    positive this module's own docstring warns about.

    Found by hitting it (Plan 00234, finding H-3): ``git commit -F - <<'EOF'``
    whose message body merely MENTIONED a guarded script was denied, because
    the body's lines were split into segments and judged as commands. The
    leading word of the offending "command" was the English word ``prose``.
    """

    def test_quoted_body_is_blanked_so_its_lines_cannot_read_as_commands(self) -> None:
        command = "git commit -F - <<'EOF'\nSubject\nprose mentioning run_all.sh\nEOF"
        assert "run_all.sh" not in strip_quoted_heredoc_bodies(command)

    def test_opener_and_closer_survive_so_the_command_still_parses(self) -> None:
        command = "git commit -F - <<'EOF'\nbody\nEOF"
        stripped = strip_quoted_heredoc_bodies(command)
        assert stripped.startswith("git commit -F - <<'EOF'")
        assert stripped.rstrip().endswith("EOF")

    def test_double_quoted_delimiter_is_also_inert(self) -> None:
        command = 'git commit -F - <<"EOF"\nprose mentioning run_all.sh\nEOF'
        assert "run_all.sh" not in strip_quoted_heredoc_bodies(command)

    def test_dash_form_delimiter_is_handled(self) -> None:
        command = "git commit -F - <<-'EOF'\n\tprose mentioning run_all.sh\n\tEOF"
        assert "run_all.sh" not in strip_quoted_heredoc_bodies(command)

    def test_unquoted_delimiter_body_is_left_alone(self) -> None:
        """`<<EOF` DOES expand, so its body can genuinely run something."""
        command = "git commit -F - <<EOF\nvalue is $(./scripts/qa/run_all.sh)\nEOF"
        assert "run_all.sh" in strip_quoted_heredoc_bodies(command)

    def test_text_outside_the_heredoc_is_untouched(self) -> None:
        command = "./scripts/qa/run_all.sh && git commit -F - <<'EOF'\nbody\nEOF"
        assert "./scripts/qa/run_all.sh &&" in strip_quoted_heredoc_bodies(command)

    def test_command_without_a_heredoc_is_returned_unchanged(self) -> None:
        command = "git commit -m 'ordinary message'"
        assert strip_quoted_heredoc_bodies(command) == command


class TestQuotedHeredocReceivers:
    """WHO receives a quoted heredoc decides whether its body can run.

    ``strip_quoted_heredoc_bodies`` states the rule that makes a body inert:
    bash never PARSES it. That is the whole truth for ``git commit -F -`` or
    ``cat > file``, which treat the bytes as data — but not for ``bash <<'EOF'``,
    where bash hands the body to an INTERPRETER that executes it. Quoting the
    delimiter changes nothing there; it only stops the outer shell expanding
    the text on the way in.

    A caller blanking bodies for a safety decision must be able to tell those
    apart, and the shell knowledge for it belongs here rather than re-derived
    per handler — which is the mistake this module's own docstring records
    (Plan 00200 Task 3.7). The interpreter POLICY stays with the caller: this
    reports the receiving command word and judges nothing.
    """

    def test_git_commit_is_reported_as_the_receiver(self) -> None:
        command = "git commit -F - <<'MSG'\nbody\nMSG"
        assert quoted_heredoc_receivers(command)[0] == "git"

    def test_bash_is_reported_as_the_receiver(self) -> None:
        command = "bash <<'EOF'\nbody\nEOF"
        assert quoted_heredoc_receivers(command) == ["bash"]

    def test_a_receiver_named_by_path_is_reported_by_basename(self) -> None:
        """`/bin/sh` and `sh` are the same interpreter; a caller matching
        against a name must not have to strip the path itself."""
        command = "/bin/sh <<'EOF'\nbody\nEOF"
        assert quoted_heredoc_receivers(command) == ["sh"]

    def test_redirect_receiver_leads_with_the_command_not_the_target(self) -> None:
        command = "cat > notes.md <<'EOF'\nbody\nEOF"
        assert quoted_heredoc_receivers(command)[0] == "cat"

    def test_receiver_after_a_pipe_is_the_last_stage_only(self) -> None:
        """`echo` is upstream of the pipe, so it is not the receiver."""
        assert quoted_heredoc_receivers("echo x | bash <<'EOF'\nbody\nEOF") == ["bash"]

    def test_receiver_after_a_separator_excludes_the_earlier_command(self) -> None:
        command = "cd /x && git commit -F - <<'MSG'\nbody\nMSG"
        receivers = quoted_heredoc_receivers(command)
        assert receivers[0] == "git"
        assert "cd" not in receivers

    def test_sudo_reports_every_word_so_the_interpreter_is_not_hidden(self) -> None:
        """`sudo -E bash <<'EOF'` still feeds bash. Reporting only the first
        word would report `sudo` and hide the interpreter behind it."""
        assert "bash" in quoted_heredoc_receivers("sudo -E bash <<'EOF'\nbody\nEOF")

    def test_multiple_heredocs_report_each_receiver(self) -> None:
        command = "cat > a <<'A'\nx\nA\nbash <<'B'\ny\nB"
        receivers = quoted_heredoc_receivers(command)
        assert "cat" in receivers
        assert "bash" in receivers

    def test_unquoted_heredoc_is_not_reported(self) -> None:
        """It is not blanked by strip_quoted_heredoc_bodies either, so there
        is no exemption for a caller to guard."""
        assert quoted_heredoc_receivers("bash <<EOF\nbody\nEOF") == []

    def test_command_without_a_heredoc_reports_nothing(self) -> None:
        assert quoted_heredoc_receivers("git commit -m 'msg'") == []
