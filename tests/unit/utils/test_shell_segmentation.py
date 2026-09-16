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
    quoted_heredoc_command_words,
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


class TestTheOpenerLineMayCarryMoreThanTheDelimiter:
    """Bash puts the redirect wherever it likes on the opener line.

    ``cat > doc.md <<'EOF'`` and ``cat <<'EOF' > doc.md`` are the SAME
    command — the heredoc opener and the output redirect are independent
    redirections, and their order carries no meaning. Only the first spelling
    was recognised: the pattern demanded a newline immediately after the
    closing quote, so anything trailing on that line (a redirect, another
    argument) meant the heredoc was not seen at all and its body was scanned
    as shell.

    That is the failure this module exists to prevent, reappearing on a
    spelling nobody thought to try: a body of English prose gets split on
    newlines and its words are judged as commands. Which of two identical
    commands is denied then depends on word order.
    """

    def test_a_redirect_after_the_delimiter_still_marks_a_heredoc(self) -> None:
        command = "cat <<'EOF' > doc.md\nprose mentioning run_all.sh\nEOF"
        assert "run_all.sh" not in strip_quoted_heredoc_bodies(command)

    def test_both_redirect_orders_agree(self) -> None:
        """The point of the fix, stated as the equivalence it restores."""
        before = strip_quoted_heredoc_bodies("cat > doc.md <<'EOF'\nprose\nEOF")
        after = strip_quoted_heredoc_bodies("cat <<'EOF' > doc.md\nprose\nEOF")

        assert "prose" not in before
        assert "prose" not in after

    def test_trailing_arguments_after_the_delimiter_are_tolerated(self) -> None:
        command = "tee -a doc.md <<'EOF' 2> errors.log\nprose mentioning run_all.sh\nEOF"
        assert "run_all.sh" not in strip_quoted_heredoc_bodies(command)

    def test_a_redirect_on_the_opener_line_survives_the_blanking(self) -> None:
        """Blanking a body must remove no evidence except the body.

        The redirect destination is exactly what handlers like
        ``project_containment`` judge, so dropping it while tidying the body
        would hide ``cat <<'EOF' > /etc/hosts`` from the check that exists to
        catch it.
        """
        stripped = strip_quoted_heredoc_bodies("cat <<'EOF' > /etc/hosts\nprose\nEOF")

        assert "> /etc/hosts" in stripped
        assert "prose" not in stripped

    def test_an_unquoted_delimiter_with_a_trailing_redirect_is_still_left_alone(
        self,
    ) -> None:
        """Widening the opener line must not widen WHICH heredocs count.

        A bare ``<<EOF`` expands, so its body can genuinely run something —
        that is why it is deliberately unmatched, and the redirect's position
        has no bearing on it.
        """
        command = "cat <<EOF > doc.md\nvalue is $(./scripts/qa/run_all.sh)\nEOF"
        assert "run_all.sh" in strip_quoted_heredoc_bodies(command)


class TestDelimitersThatAreNotPlainWords:
    """``\\w+`` is narrower than bash's rule for a delimiter.

    A quoted delimiter can hold punctuation — ``'EOF-1'``, ``'END.MD'`` are
    ordinary and legal. An unmatched delimiter is not a near miss: the heredoc
    is not recognised at all, so the whole body is scanned as shell.
    """

    def test_a_hyphenated_delimiter_is_recognised(self) -> None:
        command = "cat > doc.md <<'EOF-1'\nprose mentioning run_all.sh\nEOF-1"
        assert "run_all.sh" not in strip_quoted_heredoc_bodies(command)

    def test_a_dotted_delimiter_is_recognised(self) -> None:
        command = "cat > doc.md <<'END.MD'\nprose mentioning run_all.sh\nEND.MD"
        assert "run_all.sh" not in strip_quoted_heredoc_bodies(command)

    def test_a_body_line_that_merely_starts_with_the_delimiter_does_not_close_it(
        self,
    ) -> None:
        """``EOF`` must not be closed by a line reading ``EOFDATA``.

        Sharper than it looks once punctuation is allowed in a delimiter: a
        prefix match ends the body early, and everything after it is scanned
        as shell — the exact exposure this helper removes.
        """
        command = "cat > doc.md <<'EOF'\nfirst line\nEOFDATA mentioning run_all.sh\nEOF"
        assert "run_all.sh" not in strip_quoted_heredoc_bodies(command)


class TestABodyIsOnlyInertIfItsRECEIVERTreatsItAsData:
    """A quoted delimiter says what the OUTER shell expands, not who runs it.

    ``bash <<'EOF'`` executes its body. The quoting governs only expansion on
    the way in, so blanking the body on the strength of the delimiter alone
    hands every caller a clean bypass: the guard is shown an empty command and
    the interpreter runs the real one.

    That shipped. v3.64.0 added blanking here to stop prose describing a
    destructive command being denied (release note 29, Plan 00377 N7) and keyed
    it on the delimiter's QUOTING rather than on the heredoc's RECEIVER. The
    shipped v3.63.0 module judged the raw string and denied all five spellings
    below; the blanking allowed them.

    The remedy is the one Plan 00335 Decision 1 already reached for
    ``curl_pipe_shell``: an ALLOWLIST of data sinks. "Is the receiver
    dangerous?" makes every name nobody thought of default to safe — which it
    did four times there. "Is the receiver a recognised sink?" makes the same
    unknown default to "scan it", and withholding an exemption costs a false
    positive where granting one costs a guard.
    """

    DESTRUCTIVE = (
        "git reset --hard HEAD",
        "git checkout -- f.txt",
        "git clean -fd",
        "git push --force origin main",
        "git branch -D main",
    )

    @pytest.mark.parametrize("body", DESTRUCTIVE)
    def test_bash_heredoc_body_survives_because_bash_executes_it(self, body: str) -> None:
        assert body in strip_quoted_heredoc_bodies(f"bash <<'EOF'\n{body}\nEOF")

    @pytest.mark.parametrize(
        "receiver",
        ["bash", "sh", "/bin/sh", "zsh", "python3", "perl", "node", "ssh host"],
    )
    def test_an_unrecognised_receiver_withholds_the_exemption(self, receiver: str) -> None:
        """Not a list of interpreters — anything not a known SINK withholds.

        ``ssh host <<'EOF'`` runs the body on another machine, and no list of
        local interpreters would have contained it.
        """
        command = f"{receiver} <<'EOF'\ngit reset --hard HEAD\nEOF"
        assert "git reset --hard HEAD" in strip_quoted_heredoc_bodies(command)

    def test_sudo_does_not_hide_the_interpreter(self) -> None:
        command = "sudo -E bash <<'EOF'\ngit reset --hard HEAD\nEOF"
        assert "git reset --hard HEAD" in strip_quoted_heredoc_bodies(command)

    def test_only_the_interpreter_heredoc_of_two_keeps_its_body(self) -> None:
        """The decision is per heredoc, not per command."""
        command = "cat > a <<'A'\ngit clean -fd\nA\nbash <<'B'\ngit reset --hard HEAD\nB"
        stripped = strip_quoted_heredoc_bodies(command)

        assert "git clean -fd" not in stripped
        assert "git reset --hard HEAD" in stripped

    @pytest.mark.parametrize("interpreter", ["bash", "sh", "/bin/sh", "python3", "ssh host"])
    def test_a_sink_whose_output_is_piped_into_an_interpreter_keeps_its_body(
        self, interpreter: str
    ) -> None:
        """`cat <<'EOF' | bash` — the sink reads it, and bash then RUNS it.

        Asking only "is the receiver a sink?" answers yes here and blanks the
        body, which is a second execution channel wearing the first one's
        clothes. The exemption has to survive the whole pipeline, not just its
        first stage. `ssh host` is in the list because it is the case a
        denylist of interpreters would miss — the same argument that made
        DATA_SINKS an allowlist in the first place.
        """
        command = f"cat <<'EOF' | {interpreter}\ngit reset --hard HEAD\nEOF"
        assert "git reset --hard HEAD" in strip_quoted_heredoc_bodies(command)

    def test_a_sink_inside_a_command_substitution_keeps_its_body(self) -> None:
        """`$(cat <<'EOF' ... )` puts the body's TEXT in command position.

        The receiver is `cat` and nothing is piped on, so both other checks say
        "prose" — but bash substitutes the output and then runs it as a
        command. `command_word` deliberately strips `$(` to find the command
        inside, which is right for naming a receiver and wrong for deciding
        whether an exemption is safe.
        """
        command = "$(cat <<'EOF'\ngit reset --hard HEAD\nEOF\n)"
        assert "git reset --hard HEAD" in strip_quoted_heredoc_bodies(command)

    def test_the_backtick_spelling_of_that_substitution_is_covered_too(self) -> None:
        command = "`cat <<'EOF'\ngit reset --hard HEAD\nEOF`"
        assert "git reset --hard HEAD" in strip_quoted_heredoc_bodies(command)

    def test_a_separator_inside_the_substitution_does_not_defeat_the_check(
        self,
    ) -> None:
        """Containment is a property of the RAW text, not of the last segment.

        The check used to be anchored at the start of the receiving segment,
        and `_receiving_segment` splits on `&&`/`|`/`;` and keeps the LAST
        piece -- so any separator inside the substitution moved the `$(` out of
        the segment and the anchor stopped matching. Bash still substitutes the
        output and still runs it.
        """
        command = "$(true && cat <<'EOF'\ngit reset --hard HEAD\nEOF\n)"
        assert "git reset --hard HEAD" in strip_quoted_heredoc_bodies(command)

    def test_a_pipe_inside_the_substitution_does_not_defeat_the_check(self) -> None:
        command = "$(echo x | cat <<'EOF'\ngit reset --hard HEAD\nEOF\n)"
        assert "git reset --hard HEAD" in strip_quoted_heredoc_bodies(command)

    def test_a_separator_inside_the_backtick_spelling_is_covered_too(self) -> None:
        command = "`true && cat <<'EOF'\ngit reset --hard HEAD\nEOF`"
        assert "git reset --hard HEAD" in strip_quoted_heredoc_bodies(command)

    def test_a_closed_substitution_earlier_in_the_command_still_blanks(self) -> None:
        """Containment must END with the substitution, or prose stops blanking.

        `$(date)` closes before the heredoc opens, so the sink is NOT inside a
        substitution and an ordinary prose write keeps its exemption.
        """
        command = "echo $(date) && cat <<'EOF' > notes.md\ngit reset --hard HEAD\nEOF"
        assert "git reset --hard HEAD" not in strip_quoted_heredoc_bodies(command)

    def test_an_apostrophe_in_earlier_double_quoted_text_does_not_confuse_it(
        self,
    ) -> None:
        """A `'` inside double quotes is literal, not a quote opener."""
        command = "echo \"don't\" && cat <<'EOF' > notes.md\ngit reset --hard HEAD\nEOF"
        assert "git reset --hard HEAD" not in strip_quoted_heredoc_bodies(command)

    def test_a_plain_subshell_is_not_a_substitution_and_stays_blanked(self) -> None:
        """`( cat <<'EOF' ) > f` groups; it does not substitute.

        The output goes to a redirect, not into command position, so the body
        is still prose. Withholding here would scan every grouped prose write.
        """
        command = "( cat <<'EOF' ) > notes.md\ngit reset --hard HEAD\nEOF"
        assert "git reset --hard HEAD" not in strip_quoted_heredoc_bodies(command)

    @pytest.mark.parametrize("downstream", ["grep x", "jq -r .", "tee out.txt", "wc -l"])
    def test_a_pipeline_of_sinks_is_still_blanked(self, downstream: str) -> None:
        """Every stage reads; nothing runs. The exemption survives."""
        command = f"cat <<'EOF' | {downstream}\ngit reset --hard HEAD\nEOF"
        assert "git reset --hard HEAD" not in strip_quoted_heredoc_bodies(command)

    @pytest.mark.parametrize("interpreter", ["bash", "sh", "ssh host"])
    def test_a_stderr_redirect_does_not_hide_the_pipe_after_it(self, interpreter: str) -> None:
        """`2>&1` contains a bare `&`, and `&` used to end the pipeline scan.

        So `cat <<'EOF' 2>&1 | bash` was cut at the redirect's ampersand, the
        pipe was never seen, and the body bash runs was blanked. A stderr
        redirect is ordinary enough that this is not an exotic spelling.
        """
        command = f"cat <<'EOF' 2>&1 | {interpreter}\ngit reset --hard HEAD\nEOF"
        assert "git reset --hard HEAD" in strip_quoted_heredoc_bodies(command)

    def test_a_stderr_redirect_before_a_sink_still_blanks(self) -> None:
        """The control: fixing the redirect must not withhold from real sinks."""
        command = "cat <<'EOF' 2>&1 | grep x\ngit reset --hard HEAD\nEOF"
        assert "git reset --hard HEAD" not in strip_quoted_heredoc_bodies(command)

    @pytest.mark.parametrize(
        "receiver",
        ["cat 2>&1", "cat >&2", "git commit -F - 2>&1", "tee f 1>&2", "cat &> log"],
    )
    def test_a_redirect_ON_THE_RECEIVER_does_not_hide_which_command_it_is(
        self, receiver: str
    ) -> None:
        """The same ampersand, on the other side of the opener.

        `cat 2>&1 <<'EOF'` splits at the redirect's `&` and resolves the
        receiver to `1`, which is on no allowlist — so the exemption is
        withheld and prose gets scanned. That direction is safe, but it
        re-opens the exact false positive release note 29 existed to close:
        `git commit -F - 2>&1 <<'EOF'` describing a destructive command would
        be denied again.
        """
        command = f"{receiver} <<'EOF' > notes.md\ngit reset --hard HEAD\nEOF"
        assert "git reset --hard HEAD" not in strip_quoted_heredoc_bodies(command)

    def test_a_redirect_on_an_INTERPRETER_receiver_still_keeps_the_body(self) -> None:
        """Resolving the receiver correctly must not resolve it into safety."""
        command = "bash 2>&1 <<'EOF'\ngit reset --hard HEAD\nEOF"
        assert "git reset --hard HEAD" in strip_quoted_heredoc_bodies(command)

    def test_backgrounding_does_not_pipe_the_body_anywhere(self) -> None:
        """`cat <<'EOF' & bash` runs bash separately; it never sees the body."""
        command = "cat <<'EOF' & bash\ngit reset --hard HEAD\nEOF"
        assert "git reset --hard HEAD" not in strip_quoted_heredoc_bodies(command)

    def test_a_separator_ends_the_pipeline_rather_than_extending_it(self) -> None:
        """`||` does not feed the body to anything, so it must not withhold.

        Distinguishing this from `|` matters: treating any downstream word as a
        consumer would scan ordinary prose bodies whose opener line merely has
        a fallback branch after it.
        """
        command = "cat <<'EOF' > notes.md || echo failed\ngit reset --hard HEAD\nEOF"
        assert "git reset --hard HEAD" not in strip_quoted_heredoc_bodies(command)

    @pytest.mark.parametrize(
        "receiver",
        ["cat > notes.md", "tee -a notes.md", "git commit -F -", "jq -r .", "grep x"],
    )
    def test_a_recognised_sink_is_still_blanked(self, receiver: str) -> None:
        """Release note 29's fix must keep working — this is the whole point.

        These receivers treat the bytes as data, so a destructive command in
        the body is prose. Denying it was the false positive that prompted the
        blanking in the first place.
        """
        command = f"{receiver} <<'EOF'\ngit reset --hard HEAD\nEOF"
        assert "git reset --hard HEAD" not in strip_quoted_heredoc_bodies(command)


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


class TestQuotedHeredocCommandWords:
    """One effective command word per heredoc, for an ALLOWLIST caller.

    `quoted_heredoc_receivers` reports EVERY word so a caller matching against
    a list of dangerous names cannot be fooled by `sudo -E bash`. An allowlist
    caller needs the opposite shape: the single word naming the command, so it
    can ask "is this a recognised data sink?". Reporting arguments too would
    make `git commit -F -` fail the question on `commit`, and `jq -r .` fail
    it on `.` — which is exactly the over-block Plan 00335 removes.
    """

    def test_the_command_word_is_reported_not_its_arguments(self) -> None:
        command = "git commit -F - <<'MSG'\nbody\nMSG"
        assert quoted_heredoc_command_words(command) == ["git"]

    def test_jq_reports_jq_not_its_identity_filter(self) -> None:
        """`.` is jq's identity filter here, not the sourcing builtin."""
        command = "jq -r . <<'EOF'\nbody\nEOF"
        assert quoted_heredoc_command_words(command) == ["jq"]

    def test_sudo_is_skipped_so_the_real_command_is_reported(self) -> None:
        """Skipping `sudo` cannot hide an interpreter from an allowlist
        caller: `sudo -E bash` resolves to `bash`, which no sink list holds."""
        assert quoted_heredoc_command_words("sudo -E bash <<'EOF'\nb\nEOF") == ["bash"]
        assert quoted_heredoc_command_words("sudo -E tee /etc/x <<'EOF'\nb\nEOF") == ["tee"]

    def test_a_path_named_command_is_reduced_to_its_basename(self) -> None:
        assert quoted_heredoc_command_words("/bin/sh <<'EOF'\nb\nEOF") == ["sh"]

    def test_punctuation_is_normalised_off_the_command_word(self) -> None:
        assert quoted_heredoc_command_words("(bash <<'EOF'\nb\nEOF\n)") == ["bash"]
        assert quoted_heredoc_command_words("\"bash\" <<'EOF'\nb\nEOF") == ["bash"]

    def test_receiver_after_a_pipe_is_the_last_stage_only(self) -> None:
        assert quoted_heredoc_command_words("echo x | bash <<'EOF'\nb\nEOF") == ["bash"]

    def test_each_heredoc_contributes_one_word(self) -> None:
        command = "cat > a <<'A'\nx\nA\nbash <<'B'\ny\nB"
        assert quoted_heredoc_command_words(command) == ["cat", "bash"]

    def test_an_expansion_built_command_word_is_reported_verbatim(self) -> None:
        """Not resolved -- resolving it would mean running the command. It is
        reported as-is so an allowlist caller simply fails to match it, which
        is the safe direction and is why the expansion family needs no
        normalisation."""
        assert quoted_heredoc_command_words("$SHELL <<'EOF'\nb\nEOF") == ["SHELL"]

    def test_unquoted_heredoc_is_not_reported(self) -> None:
        assert quoted_heredoc_command_words("bash <<EOF\nbody\nEOF") == []

    def test_command_without_a_heredoc_reports_nothing(self) -> None:
        assert quoted_heredoc_command_words("git commit -m 'msg'") == []
