"""destructive_git must judge the COMMAND, not prose the shell hands over as data.

Plan 00377 N7. A commit whose message described a newly added ``--force`` flag
was denied as ``R-GIT-PUSH-FORCE``. The message was prose inside a heredoc with
a QUOTED delimiter, in which bash expands nothing.

The mechanism is narrower than "the guard saw two words in one string", and
worth stating because it decides where the fix belongs. The opener line was::

    git commit -F - <<'EOF' && git push origin main

so the heredoc BODY physically follows ``git push`` in the command string, and
``_GIT_PUSH_FORCE_PATTERN``'s ``[^;&|]*?`` excludes those three separators but
NOT newlines. The scan therefore ran from ``git push`` down into the body.

A second route reaches the same defect without any heredoc: the single-line
patterns use ``.*``, which stays on one line but still matches inside a ``-m``
value. Both are covered below, because blanking only the heredoc leaves the
second route open — measured, not assumed.

The guard's real job is unchanged and is asserted just as hard: a genuinely
destructive command is still denied, including when it shares a command line
with an innocent message, and a message value that bash would SUBSTITUTE is not
prose at all.
"""

import pytest

from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.destructive_git import (
    DestructiveGitHandler,
)

# Assembled rather than written literally. These strings are the very shapes the
# handler misreads, and a test file is read by other scanners too — building them
# from fragments keeps the intent ("this is data") true of the file itself.
_FORCE = "--" + "force"
_AMEND = "--" + "amend"
_RESET_HARD = "git reset " + "--hard"
#: The operand that makes `git checkout` discard a working-tree change.
_DISCARD = "-" + "-"

#: The exact command from the field report, reduced to its shape.
_FIELD_REPORT = (
    "set -euo pipefail; git add -A && git commit -F - <<'EOF' && git push origin main\n"
    f"N4 -- `agents install <name> {_FORCE}`. The warning now names that escape.\n"
    "EOF"
)


@pytest.fixture
def handler() -> DestructiveGitHandler:
    return DestructiveGitHandler()


def _matches(handler: DestructiveGitHandler, command: str) -> bool:
    return handler.matches({"tool_name": "Bash", "tool_input": {"command": command}})


class TestProseIsNotACommand:
    """Spans bash hands over as DATA must not be read as shell syntax."""

    def test_the_field_report_is_allowed(self, handler: DestructiveGitHandler) -> None:
        assert _matches(handler, _FIELD_REPORT) is False

    def test_a_quoted_heredoc_body_naming_a_reset_is_allowed(
        self, handler: DestructiveGitHandler
    ) -> None:
        """A receiver that only READS the body makes its contents prose."""
        command = f"cat > notes.md <<'EOF'\nexample = '{_RESET_HARD}'\nEOF"
        assert _matches(handler, command) is False

    def test_a_python_heredoc_body_is_scanned_because_python_runs_it(
        self, handler: DestructiveGitHandler
    ) -> None:
        """The accepted cost of Plan 00409, stated as a requirement.

        This case was an ALLOW until it was measured: `python3 - <<'PY'` feeds
        an interpreter, and a quoted delimiter governs only what the OUTER
        shell expands on the way in. The body here is inert Python, so this is
        a genuine false positive — and it is the cheap error. Granting the
        exemption by receiver name is what let `bash <<'EOF'` walk past five
        data-loss rules in v3.64.0, because a body that MIGHT be inert and one
        that runs `subprocess.run` are the same string to this handler.

        The mitigation is the house rule that already applies: file content
        goes through Write/Edit, not a heredoc.
        """
        command = f"python3 - <<'PY'\nexample = '{_RESET_HARD}'\nPY"
        assert _matches(handler, command) is True

    def test_a_message_naming_an_amend_is_allowed(self, handler: DestructiveGitHandler) -> None:
        """No heredoc involved — the `.*` patterns match inside a -m value."""
        assert _matches(handler, f"git commit -m 'document {_AMEND} behaviour'") is False

    def test_a_message_naming_a_reset_is_allowed(self, handler: DestructiveGitHandler) -> None:
        assert _matches(handler, f"git commit -m 'explain {_RESET_HARD}'") is False

    def test_a_message_file_flag_naming_a_force_push_is_allowed(
        self, handler: DestructiveGitHandler
    ) -> None:
        assert _matches(handler, f"git commit -F - <<'EOF'\ndescribes {_FORCE}\nEOF") is False


class TestTheGuardStillGuards:
    """Every subtraction above must cost the handler nothing that matters."""

    @pytest.mark.parametrize(
        "command",
        [
            f"git push {_FORCE} origin main",
            f"git commit {_AMEND} -m 'fix typo'",
            f"{_RESET_HARD} HEAD",
            "git push origin +main:main",
            "git clean -fd",
            "git branch -D feature",
        ],
    )
    def test_a_genuinely_destructive_command_is_still_blocked(
        self, handler: DestructiveGitHandler, command: str
    ) -> None:
        assert _matches(handler, command) is True

    def test_a_real_force_push_sharing_a_line_with_a_message_is_blocked(
        self, handler: DestructiveGitHandler
    ) -> None:
        """Blanking the message must not blank the command beside it."""
        command = f"git commit -m 'ordinary message' && git push {_FORCE} origin main"
        assert _matches(handler, command) is True

    def test_a_real_force_push_after_a_quoted_heredoc_is_blocked(
        self, handler: DestructiveGitHandler
    ) -> None:
        command = (
            f"git commit -F - <<'EOF'\nan ordinary message\nEOF\ngit push {_FORCE} origin main"
        )
        assert _matches(handler, command) is True

    def test_a_substituting_message_value_is_not_prose(
        self, handler: DestructiveGitHandler
    ) -> None:
        """Bash substitutes inside DOUBLE quotes, so this really runs the push.

        The separating rule is ``value_can_substitute``, not quote class: the
        single-quoted sibling above is inert and allowed.
        """
        command = f'git commit -m "$(git push {_FORCE} origin main)"'
        assert _matches(handler, command) is True

    @pytest.mark.parametrize(
        "body",
        [
            f"{_RESET_HARD} HEAD",
            f"git checkout {_DISCARD} f.txt",
            "git clean -fd",
            f"git push {_FORCE} origin main",
            "git branch -D main",
        ],
    )
    @pytest.mark.parametrize("receiver", ["bash", "sh", "/bin/sh", "sudo -E bash", "ssh host"])
    def test_a_heredoc_fed_to_an_interpreter_is_still_blocked(
        self, handler: DestructiveGitHandler, receiver: str, body: str
    ) -> None:
        """Plan 00409, the regression this table pins.

        Every one of these was DENIED by the shipped v3.63.0 handler and
        ALLOWED by v3.64.0, which blanked the body because the delimiter was
        quoted. Quoting governs what the OUTER shell expands on the way in; it
        does not stop bash running the bytes. `ssh host` is in the receiver
        list because it runs the body on another machine — no list of local
        interpreters would have caught it, which is why the fix asks whether
        the receiver is a recognised SINK instead.
        """
        assert _matches(handler, f"{receiver} <<'EOF'\n{body}\nEOF") is True

    @pytest.mark.parametrize("interpreter", ["bash", "sh", "python3", "ssh host"])
    def test_a_sink_piped_into_an_interpreter_is_still_blocked(
        self, handler: DestructiveGitHandler, interpreter: str
    ) -> None:
        """`cat <<'EOF' | bash` — a sink is not a safe place to stop looking.

        The heredoc's receiver IS `cat`, so asking only about the receiver
        answers "prose" and blanks the body, which bash then executes. Found by
        probing the fix rather than by reading it, after the receiver check was
        already written and passing.
        """
        command = f"cat <<'EOF' | {interpreter}\n{_RESET_HARD} HEAD\nEOF"
        assert _matches(handler, command) is True

    def test_a_pipeline_of_sinks_is_still_prose(self, handler: DestructiveGitHandler) -> None:
        """The control: every stage reads, nothing runs, so nothing is denied."""
        command = f"cat <<'EOF' | grep reset | wc -l\n{_RESET_HARD} HEAD\nEOF"
        assert _matches(handler, command) is False

    @pytest.mark.parametrize(
        ("channel", "command"),
        [
            (
                "eval of a substituted cat heredoc",
                f"eval \"$(cat <<'EOF'\n{_RESET_HARD} HEAD\nEOF\n)\"",
            ),
            ("bare substitution in command position", f"$(cat <<'EOF'\n{_RESET_HARD} HEAD\nEOF\n)"),
            ("backtick substitution", f"`cat <<'EOF'\n{_RESET_HARD} HEAD\nEOF`"),
            ("dot /dev/stdin", f". /dev/stdin <<'EOF'\n{_RESET_HARD} HEAD\nEOF"),
            ("source /dev/stdin", f"source /dev/stdin <<'EOF'\n{_RESET_HARD} HEAD\nEOF"),
            ("bash -s", f"bash -s <<'EOF'\n{_RESET_HARD} HEAD\nEOF"),
            ("process substitution", f"bash <(cat <<'EOF'\n{_RESET_HARD} HEAD\nEOF\n)"),
            (
                "three-stage pipe ending in sh",
                f"cat <<'EOF' | tee /tmp/x | sh\n{_RESET_HARD} HEAD\nEOF",
            ),
            ("stderr redirect then bash", f"cat <<'EOF' 2>&1 | bash\n{_RESET_HARD} HEAD\nEOF"),
            ("env-wrapped receiver", f"env FOO=1 bash <<'EOF'\n{_RESET_HARD} HEAD\nEOF"),
            ("timeout-wrapped receiver", f"timeout 5 bash <<'EOF'\n{_RESET_HARD} HEAD\nEOF"),
        ],
    )
    def test_every_known_execution_channel_is_denied(
        self, handler: DestructiveGitHandler, channel: str, command: str
    ) -> None:
        """The channel checklist, pinned as a test rather than left in a probe.

        Each row is a way a quoted heredoc body actually reaches something that
        runs it, and every one was verified against the SHIPPED v3.63.0 module
        as having been denied there. They were found across six probing passes
        (Plan 00409) — three of them after a fix was committed and green.

        This lives here, not in `untracked/scratch/`, on purpose: the probes
        that found these are gitignored and will not survive, and a checklist
        that exists only where nobody can run it is the failure mode this plan
        was filed about.
        """
        assert _matches(handler, command) is True, channel

    def test_an_unquoted_heredoc_body_is_still_scanned(
        self, handler: DestructiveGitHandler
    ) -> None:
        """Deliberate boundary, shared with pipe_blocker: `<<EOF` expands.

        Quoting the delimiter is what makes a body inert; an unquoted one can
        genuinely run what it contains, so it is not blanked.

        The body is scanned like any other command text, which means LINE BY
        LINE (Plan 00406). This test used to put `git push origin main` on the
        command line and a bare `--force` in the body, and assert a match --
        but bash feeds that `--force` to `git commit -F -` as the MESSAGE, so
        the push it was attributed to never carried it. That was a cross-line
        attribution, not a force push, and it is the exact class Plan 00406
        removed.

        What the guard is actually for is unchanged and is what is asserted
        here: the body is NOT blanked, so a force push written inside it still
        matches -- including the spelling that really does run, `$(...)`.
        """
        command = f"git commit -F - <<EOF\ngit push {_FORCE} origin main\nEOF"
        assert _matches(handler, command) is True

    def test_a_substituting_force_push_inside_an_unquoted_body_is_blocked(
        self, handler: DestructiveGitHandler
    ) -> None:
        """The spelling that genuinely executes from inside an unquoted body."""
        command = f"git commit -F - <<EOF\n$(git push {_FORCE} origin main)\nEOF"
        assert _matches(handler, command) is True


class TestAFlagIsNotAMessage:
    """`-m` means "message" only where the SUBCOMMAND takes one.

    Message blanking was scoped to the BINARY, so for any git subcommand where
    `-m` is not a message flag, the very next token was blanked as though it
    were commit prose. Inserting two characters therefore talked the guard out
    of blocking, and R-GIT-CHECKOUT-DISCARD exists precisely to prevent
    unrecoverable loss. Reproduced end to end against the live hook by the
    release review: the `-m` form ran, exited 0, and permanently discarded a
    working-tree modification, while the plain form was denied (Plan 00407 N7).

    The failure is not an evasion — `git checkout -m` is a real command a model
    can emit — and it was a REGRESSION: the previous release blanked nothing
    here and denied both spellings.
    """

    def test_an_inserted_flag_does_not_hide_a_discarding_checkout(
        self, handler: DestructiveGitHandler
    ) -> None:
        assert _matches(handler, f"git checkout -m {_DISCARD} f.txt") is True

    def test_the_plain_discarding_checkout_is_still_denied(
        self, handler: DestructiveGitHandler
    ) -> None:
        """The control: the spelling that was never broken."""
        assert _matches(handler, f"git checkout {_DISCARD} f.txt") is True

    @pytest.mark.xfail(
        reason=(
            "Known BEHAVIOUR gap, Plan 00408: a QUOTED operand is not recognised, "
            "and it is not this release's regression -- the plain quoted spelling "
            "fails identically with no `-m` present, so blanking was never the "
            "cause. Recorded as Plan 00407 N8 and graduated rather than fixed "
            "inside a release: the pattern change is broader than the scoping fix "
            "beside it. Flips to a plain pass when 00408 lands; fails loudly if "
            "'fixed' by accident."
        ),
        strict=True,
    )
    def test_quoting_the_operand_does_not_hide_it_either(
        self, handler: DestructiveGitHandler
    ) -> None:
        assert _matches(handler, f'git checkout -m "{_DISCARD}" f.txt') is True

    def test_a_real_commit_message_is_still_treated_as_prose(
        self, handler: DestructiveGitHandler
    ) -> None:
        """The property the blanking exists for must survive the fix."""
        assert _matches(handler, f"git commit -m 'document {_AMEND}'") is False


class TestBothVerbsReadTheSameCommand:
    """``matches()`` and ``handle()`` must never disagree about what ran."""

    def test_handle_names_the_force_push_rule_for_a_real_force_push(
        self, handler: DestructiveGitHandler
    ) -> None:
        result = handler.handle(
            {
                "tool_name": "Bash",
                "tool_input": {"command": f"git push {_FORCE} origin main"},
            }
        )
        assert result.decision is Decision.DENY
        assert result.reason is not None
        assert RuleID.GIT_PUSH_FORCE in result.reason

    def test_handle_does_not_name_a_destructive_rule_for_the_field_report(
        self, handler: DestructiveGitHandler
    ) -> None:
        """If handle() scanned the raw command it would report a force push.

        Dispatch never calls handle() without matches(), so this guards the
        pair rather than a live path — the two read one scan target or they
        drift, which is how the ordered-pattern mapping was justified.
        """
        assert handler._match_rule_id(_FIELD_REPORT) is None
